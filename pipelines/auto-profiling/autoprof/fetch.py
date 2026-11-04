"""fetch: one small, reusable sample per group representative → raw/samples/, raw/sniff.json.

Samples are cached in cache/ by URL plus ETag or Last-Modified, so a rerun only
refetches what changed (scripts/run.sh wipes raw/ before every fetch).
"""
import asyncio
import io
import hashlib
import json
import os
import re
import shutil
import struct
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import httpx
from lxml import etree

from . import formats
from .config import Config
from .http import Client
from .log import log
from .sniff import HEAD_BYTES, encoding, sniff

EXT = {"PARQUET": "parquet", "CSV": "csv", "TSV": "tsv", "XLSX": "xlsx", "XLS": "xls", "ODS": "ods",
       "GPKG": "gpkg", "ZIP": "zip", "JSON": "json", "JSONL": "jsonl", "JSON_LD": "jsonld",
       "XML": "xml", "GML": "gml", "RDF_TURTLE": "ttl", "N3": "n3", "NT": "nt", "RDF_XML": "rdf",
       "PX": "px", "PXWEB": "json", "TXT": "txt"}
LINE_BASED = {"CSV", "TSV", "JSONL", "RDF_TURTLE", "N3", "NT"}
TRUNCATABLE = {"XML"}                      # parsed with recovery, so a cut-off sample still works
WHOLE_FILE = {"XLSX", "XLS", "ODS", "GPKG", "PX", "JSON", "JSON_LD", "PXWEB", "GML", "RDF_XML", "ZIP"}
ZIP_MEMBERS = [(".gpkg", "GPKG"), (".shp", "SHP"), (".gml", "GML"), (".csv", "CSV"), (".xlsx", "XLSX"),
               (".xls", "XLS"), (".ods", "ODS"), (".parquet", "PARQUET"), (".json", "JSON"),
               (".xml", "XML"), (".px", "PX"), (".ttl", "RDF_TURTLE")]
EQUIVALENT = [{"JSON", "JSONL", "PXWEB"}, {"PX", "PXWEB"}, {"XML", "GML", "WFS"}, {"CSV", "TSV", "TXT"},
              {"RDF_TURTLE", "N3"}]
PX_LANGS = ["de", "fr", "it", "en"]


class Skip(Exception):
    """The distribution is out of reach or out of scope: skipped(reason)."""


class Fail(Exception):
    """Something went wrong: failed(reason)."""


@dataclass
class Result:
    distribution: str
    url: str | None
    declared: list
    sniffed: str | None = None
    match: bool | None = None
    httpStatus: int | None = None
    contentType: str | None = None
    bytes: int | None = None
    sample: str | None = None              # relative to the pipeline folder
    status: str = "ok"                     # ok / skipped / failed
    reason: str | None = None
    truncated: bool = False
    seconds: float = 0
    cached: bool = False
    detail: dict = field(default_factory=dict)
    tried: list = field(default_factory=list)   # earlier candidates that failed


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def matches(sniffed: str | None, declared: list, detail: dict) -> bool | None:
    if not sniffed or not declared:
        return None
    candidates = {sniffed, detail.get("inner")}
    if sniffed in declared or detail.get("inner") in declared:
        return True
    if "ZIP" in declared and detail.get("inner"):
        return True
    return any(candidates & group and set(declared) & group for group in EQUIVALENT)


# --- ZIP central directory -------------------------------------------------------

def zip_members(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        return [i.filename for i in z.infolist() if not i.is_dir()]


def pick_member(members: list[str]) -> tuple[str | None, str | None]:
    lowered = [m.lower() for m in members if not m.startswith("__MACOSX")]
    for suffix, token in ZIP_MEMBERS:
        for m, low in zip(members, lowered):
            if low.endswith(suffix):
                return m, token
    return None, None


def sparse_file(path: Path, size: int, tail: bytes) -> None:
    """A file of `size` bytes holding only its last bytes; enough for ZIP and Parquet footers."""
    with open(path, "wb") as f:
        f.truncate(size)
        f.seek(size - len(tail))
        f.write(tail)


# --- the fetcher -----------------------------------------------------------------

class Fetcher:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.max = cfg.max_bytes
        self.deadline = cfg.int("FETCH_DEADLINE")
        self.rows = cfg.int("SAMPLE_ROWS")
        self.samples = cfg.raw / "samples"
        self.cache_dir = cfg.cache / "samples"
        self.cache_file = cfg.cache / "cache.json"
        self.cache = json.loads(self.cache_file.read_text()) if self.cache_file.exists() else {}
        self.client = None

    def rel(self, path: Path) -> str:
        return str(path.relative_to(self.cfg.pipeline_dir))

    async def run(self, groups: list[dict], dists: dict) -> dict:
        self.samples.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = Client(self.cfg.int("CONCURRENCY"), self.cfg.int("PER_HOST"), self.cfg.int("HTTP_TIMEOUT"),
                             self.deadline)
        try:
            results = await asyncio.gather(*(self.group(g, dists) for g in groups))
        finally:
            await self.client.close()
        self.cache_file.write_text(json.dumps(self.cache, indent=1))
        return {g["id"]: asdict(r) for g, r in zip(groups, results)}

    async def group(self, g: dict, dists: dict) -> Result:
        """Try the representative, then the fallbacks; keep the first that works."""
        candidates = g["candidates"] or [g["representative"]]
        tried, result = [], None
        for iri in candidates:
            result = await self.one(g["id"], dists[iri])
            if result.status == "ok":
                break
            tried.append({"distribution": iri, "status": result.status, "reason": result.reason})
        result.tried = tried[:-1] if result.status != "ok" else tried
        log(f"  {g['id']} {result.status:7} {result.sniffed or '-':10} "
            f"{result.reason or ''} {result.url or ''}"[:200])
        return result

    async def one(self, gid: str, d: dict) -> Result:
        r = Result(distribution=d["iri"], url=d["url"], declared=d["declared"])
        start = time.monotonic()
        try:
            if not d["url"]:
                raise Skip("no-url")
            if not formats.worth_fetching(d["declared"]):
                raise Skip("out-of-scope:" + "|".join(d["declared"]))
            if api := formats.pxweb_api(d["url"]):
                await self.pxweb(gid, api, r)
            elif "WFS" in d["declared"] or formats.from_url(d["url"]) == "WFS":
                await self.wfs(gid, d["url"], r)
            else:
                await self.generic(gid, d["url"], r)
            r.match = matches(r.sniffed, r.declared, r.detail)
        except Skip as e:
            r.status, r.reason = "skipped", str(e)
        except Fail as e:
            r.status, r.reason = "failed", str(e)
        except httpx.TimeoutException:
            r.status, r.reason = "failed", "timeout"
        except TimeoutError:
            r.status, r.reason = "failed", f"timeout:{self.deadline}s"
        except httpx.HTTPError as e:
            r.status, r.reason = "failed", f"http-error:{type(e).__name__}"
        except Exception as e:      # noqa: BLE001 - a broken sample must not stop the run
            r.status, r.reason = "failed", f"error:{type(e).__name__}:{e}"[:300]
        r.seconds = round(time.monotonic() - start, 2)
        return r

    # --- generic downloads ---

    async def head(self, url: str) -> dict:
        try:
            h = await self.client.request("HEAD", url)
        except httpx.HTTPError:
            return {}
        if h.status_code >= 400:
            return {}
        length = h.headers.get("content-length")
        return {"etag": h.headers.get("etag"), "lastModified": h.headers.get("last-modified"),
                "length": int(length) if length and length.isdigit() else None,
                "ranges": h.headers.get("accept-ranges", "").lower() == "bytes",
                "contentType": h.headers.get("content-type"), "finalUrl": str(h.url)}

    def cached(self, url: str, head: dict) -> dict | None:
        c = self.cache.get(url)
        if not c or not (head.get("etag") or head.get("lastModified")):
            return None
        if (c.get("etag"), c.get("lastModified")) != (head.get("etag"), head.get("lastModified")):
            return None
        return c if Path(self.cfg.pipeline_dir / c["path"]).exists() else None

    def keep(self, gid: str, url: str, head: dict, src: Path, r: Result) -> None:
        """Link the cached sample into raw/samples/ and remember it."""
        dst = self.samples / f"{gid}{''.join(src.suffixes[-1:])}"
        dst.unlink(missing_ok=True)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy(src, dst)
        r.sample = self.rel(dst)
        self.cache[url] = {"etag": head.get("etag"), "lastModified": head.get("lastModified"),
                           "path": self.rel(src), "sniffed": r.sniffed, "detail": r.detail,
                           "bytes": r.bytes, "truncated": r.truncated, "contentType": r.contentType,
                           "httpStatus": r.httpStatus}

    async def generic(self, gid: str, url: str, r: Result) -> None:
        head = await self.head(url)
        if c := self.cached(url, head):
            r.sniffed, r.detail, r.bytes, r.truncated = c["sniffed"], c["detail"], c["bytes"], c["truncated"]
            r.contentType, r.httpStatus, r.cached = c.get("contentType"), c.get("httpStatus"), True
            self.keep(gid, url, head, self.cfg.pipeline_dir / c["path"], r)
            return

        base = self.cache_dir / url_hash(url)
        tail = None
        # The deadline starts once the request holds its slot: httpx times out per read only,
        # and a server that trickles data would otherwise hold the slot for ever.
        async with self.client.stream("GET", url) as resp, asyncio.timeout(self.deadline):
            r.httpStatus = resp.status_code
            r.contentType = resp.headers.get("content-type")
            if resp.status_code >= 400:
                raise Fail(f"http-{resp.status_code}")
            length = head.get("length")
            if length is None and (cl := resp.headers.get("content-length")) and cl.isdigit() \
                    and not resp.headers.get("content-encoding"):
                length = int(cl)
            chunks = resp.aiter_bytes()
            first = bytearray()
            async for chunk in chunks:
                first += chunk
                if len(first) >= HEAD_BYTES:
                    break
            token, detail = sniff(bytes(first), r.contentType)
            if token == "OLE" and "XLS" in r.declared:
                token = "XLS"           # the OLE directory lies beyond the head; trust the metadata
            r.sniffed, r.detail = token, detail
            if token == "HTML":
                raise Fail("html-page")
            if token is None:
                raise Fail(detail.get("reason", "unrecognised"))

            # Large files with byte ranges: read the footer only.
            if token in ("ZIP", "PARQUET") and length and length > self.max and head.get("ranges"):
                tail = (token, length)
            elif token not in formats.IN_SCOPE | {"ZIP", "PXWEB"}:
                raise Skip(f"out-of-scope:{token}")
            elif length and length > self.max and token in WHOLE_FILE:
                raise Skip("too-large")
            else:
                path = base.with_suffix("." + EXT[token])
                if token in LINE_BASED:
                    await self.lines(bytes(first), chunks, path, token, r)
                else:
                    await self.whole(bytes(first), chunks, path, token in TRUNCATABLE, r)

        if tail:
            # Outside the stream: a second request to the host must not wait for our own slot.
            token, length = tail
            path = base.with_suffix("." + EXT[token])
            async with asyncio.timeout(self.deadline):
                await self.tail_only(url, token, length, path, r)
            r.bytes = length
            self.keep(gid, url, head, path, r)
            return


        if token in ("CSV", "TSV"):
            r.detail["encoding"] = encoding(path.read_bytes()[:HEAD_BYTES])
        if token == "ZIP":
            self.inspect_zip(path, r)
        self.keep(gid, url, head, path, r)
        if token == "XML" and r.detail.get("schemaLocation"):
            await self.xsd(url, r)

    async def xsd(self, url: str, r: Result) -> None:
        """The XSD an XML sample names (xsi:schemaLocation), saved beside it as <sample>.xsd."""
        locations = [u for u in r.detail["schemaLocation"].split() if u.lower().split("?")[0].endswith(".xsd")]
        if not locations:
            return
        xsd_url = httpx.URL(url).join(locations[0])
        try:
            resp = await self.client.request("GET", str(xsd_url))
        except httpx.HTTPError:
            r.detail["xsd"] = "unreachable"
            return
        if resp.status_code >= 400 or len(resp.content) > 2 * 1024 * 1024 or b"schema" not in resp.content[:4096]:
            r.detail["xsd"] = f"unusable:{resp.status_code}"
            return
        (self.cfg.pipeline_dir / (r.sample + ".xsd")).write_bytes(resp.content)
        r.detail["xsd"] = str(xsd_url)

    async def lines(self, first: bytes, chunks, path: Path, token: str, r: Result) -> None:
        """Stream until SAMPLE_ROWS lines (plus a header) or the size limit; cut at a line end."""
        buf = bytearray(first)
        limit = self.rows + 1
        if token in ("RDF_TURTLE", "N3", "NT"):
            limit = self.rows * 10      # triples, not rows
        newlines = buf.count(b"\n")
        exhausted = False
        if newlines < limit and len(buf) < self.max:
            async for chunk in chunks:
                buf += chunk
                newlines += chunk.count(b"\n")
                if newlines >= limit or len(buf) >= self.max:
                    break
            else:
                exhausted = True
        if newlines >= limit or not exhausted:
            cut = _nth_newline(buf, limit) if newlines >= limit else buf.rfind(b"\n") + 1
            r.truncated = cut < len(buf) or not exhausted
            buf = buf[:cut]
            if token in ("RDF_TURTLE", "N3") and r.truncated:
                buf = _turtle_cut(bytes(buf))
        r.bytes = len(buf)
        path.write_bytes(bytes(buf))

    async def whole(self, first: bytes, chunks, path: Path, truncatable: bool, r: Result) -> None:
        size = len(first)
        with open(path, "wb") as f:
            f.write(first)
            async for chunk in chunks:
                if size + len(chunk) > self.max:
                    if not truncatable:
                        f.close()
                        path.unlink()
                        raise Skip("too-large")
                    f.write(chunk[:self.max - size])
                    size = self.max
                    r.truncated = True
                    break
                f.write(chunk)
                size += len(chunk)
        r.bytes = size

    async def tail_only(self, url: str, token: str, length: int, path: Path, r: Result) -> None:
        if token == "PARQUET":
            end = await self.range(url, length - 8, length - 1)
            footer_len = struct.unpack("<I", end[:4])[0]
            if end[4:] != b"PAR1" or footer_len + 8 > min(length, self.max):
                raise Fail("parquet-footer")
            tail = await self.range(url, length - footer_len - 8, length - 1)
            sparse_file(path, length, tail)
            r.detail["footerOnly"] = True
            return
        # ZIP: the central directory sits at the end; list members without the data.
        for size in (64 * 1024, 4 * 1024 * 1024):
            tail = await self.range(url, max(0, length - size), length - 1)
            sparse_file(path, length, tail)
            try:
                members = zip_members(path)
                break
            except zipfile.BadZipFile:
                continue
        else:
            raise Fail("zip-central-directory")
        member, inner = pick_member(members)
        r.detail.update({"members": members[:50], "member": member, "inner": inner})
        raise Skip(f"too-large:zip({inner or 'no-supported-member'})")

    async def range(self, url: str, start: int, end: int) -> bytes:
        resp = await self.client.request("GET", url, headers={"Range": f"bytes={start}-{end}"})
        if resp.status_code != 206:
            raise Fail(f"range-http-{resp.status_code}")
        return resp.content

    def inspect_zip(self, path: Path, r: Result) -> None:
        try:
            members = zip_members(path)
        except zipfile.BadZipFile:
            raise Fail("bad-zip")
        member, inner = pick_member(members)
        r.detail.update({"members": members[:50], "member": member, "inner": inner})
        if not inner:
            raise Skip("zip-without-supported-member")

    # --- services ---

    async def pxweb(self, gid: str, api: str, r: Result) -> None:
        """PxWeb: table metadata per language plus a one-cell PX for keywords (units, time)."""
        directory = self.samples / f"{gid}.pxweb"
        directory.mkdir(parents=True, exist_ok=True)
        r.url = api
        resp = await self.client.request("GET", api)
        r.httpStatus, r.contentType = resp.status_code, resp.headers.get("content-type")
        if resp.status_code >= 400:
            raise Fail(f"http-{resp.status_code}")
        token, detail = sniff(resp.content[:HEAD_BYTES], r.contentType)
        if token != "PXWEB":
            raise Fail(f"not-pxweb:{token}")
        meta = resp.json()
        lang = re.search(r"/api/v1/([a-z]{2})/", api).group(1)
        (directory / f"meta-{lang}.json").write_bytes(resp.content)
        r.sniffed, r.detail, r.bytes = "PXWEB", detail, len(resp.content)

        query = {"query": [{"code": v["code"], "selection": {"filter": "item", "values": v["values"][:1]}}
                           for v in meta["variables"]], "response": {"format": "px"}}
        px = await self.client.request("POST", api, json=query)
        if px.status_code < 400 and px.content:
            (directory / "keywords.px").write_bytes(px.content)
        for other in PX_LANGS:
            if other == lang:
                continue
            o = await self.client.request("GET", api.replace(f"/api/v1/{lang}/", f"/api/v1/{other}/", 1))
            if o.status_code < 400 and o.content.lstrip().startswith(b"{"):
                (directory / f"meta-{other}.json").write_bytes(o.content)
        r.sample = self.rel(directory)

    async def wfs(self, gid: str, url: str, r: Result) -> None:
        """WFS: capabilities, then DescribeFeatureType and a GetFeature sample per layer."""
        u = urlparse(url)
        keep = [(k, v) for k, v in parse_qsl(u.query)
                if k.lower() not in {"service", "request", "version", "typename", "typenames", "acceptversions"}]
        base = urlunparse(u._replace(query=urlencode(keep)))
        sep = "&" if keep else "?"
        directory = self.samples / f"{gid}.wfs"
        directory.mkdir(parents=True, exist_ok=True)

        caps = await self.client.request("GET", f"{base}{sep}service=WFS&request=GetCapabilities")
        r.httpStatus, r.contentType = caps.status_code, caps.headers.get("content-type")
        if caps.status_code >= 400:
            raise Fail(f"http-{caps.status_code}")
        token, detail = sniff(caps.content[:HEAD_BYTES], r.contentType)
        if token != "WFS":
            raise Fail("html-page" if token == "HTML" else f"not-wfs-capabilities:{token}")
        (directory / "capabilities.xml").write_bytes(caps.content)
        root = etree.fromstring(caps.content, etree.XMLParser(recover=True, huge_tree=True))
        version = root.get("version", "2.0.0")
        names = [e.text.strip() for e in root.iter("{*}FeatureType") for e in e.iterfind("{*}Name") if e.text]
        r.sniffed, r.detail = "WFS", {"version": version, "layers": len(names), "root": detail.get("root")}
        if not names:
            raise Fail("wfs-without-layers")
        limit = self.cfg.int("WFS_MAX_LAYERS")
        r.detail["sampledLayers"] = min(len(names), limit)
        count = self.cfg.int("WFS_FEATURES")
        two = version.startswith("2")
        dft_base, dft_sep = operation_url(root, "DescribeFeatureType", base, sep)
        gf_base, gf_sep = operation_url(root, "GetFeature", base, sep)
        total, layers = len(caps.content), []
        for name in names[:limit]:
            stem = re.sub(r"[^\w.-]+", "_", name)
            tn = "typeNames" if two else "typeName"
            n = "count" if two else "maxFeatures"
            q = f"service=WFS&version={version}"
            dft = await self.client.request("GET", f"{dft_base}{dft_sep}{q}&request=DescribeFeatureType&{tn}={quote(name)}")
            if dft.status_code < 400 and dft.content.lstrip().startswith(b"<"):
                (directory / f"{stem}.xsd").write_bytes(dft.content)
            try:
                gf = await self.client.request(
                    "GET", f"{gf_base}{gf_sep}{q}&request=GetFeature&{tn}={quote(name)}&{n}={count}")
            except httpx.HTTPError as e:
                layers.append({"name": name, "status": f"failed:{type(e).__name__}"})
                continue
            if gf.status_code >= 400 or len(gf.content) > self.max:
                layers.append({"name": name, "status": "failed:http-" + str(gf.status_code)
                               if gf.status_code >= 400 else "skipped:too-large"})
                continue
            root_tag = etree.QName(_xml_root(gf.content[:HEAD_BYTES]) or "x").localname
            if root_tag not in FEATURE_ROOTS:
                # e.g. a server answering with its capabilities or an ExceptionReport
                layers.append({"name": name, "status": f"failed:not-features:{root_tag}"})
                continue
            (directory / f"{stem}.gml").write_bytes(gf.content)
            total += len(gf.content)
            layers.append({"name": name, "file": f"{stem}.gml", "status": "ok"})
        r.detail["layerFiles"] = layers
        r.bytes = total
        r.sample = self.rel(directory)
        if not any(l["status"] == "ok" for l in layers):
            raise Fail("wfs-getfeature")


FEATURE_ROOTS = {"FeatureCollection", "SimpleFeatureCollection"}


def operation_url(caps, op: str, base: str, sep: str) -> tuple[str, str]:
    """The GET address the capabilities advertise for op (base and query separator), else the capabilities URL."""
    for e in caps.iter("{*}Operation"):
        if e.get("name") == op:
            href = next((g.get("{http://www.w3.org/1999/xlink}href") for g in e.iter("{*}Get")), None)
            break
    else:   # WFS 1.0: <Capability><Request><GetFeature><DCPType><HTTP><Get onlineResource=...>
        href = next((g.get("onlineResource") for r in caps.iter(f"{{*}}{op}") for g in r.iter("{*}Get")), None)
    if not href or not href.startswith(("http://", "https://")):
        return base, sep
    href = href.rstrip("?&")
    return href, "&" if "?" in href else "?"


def _xml_root(head: bytes) -> str | None:
    """The tag of the root element, read from the start of a document."""
    try:
        for _, el in etree.iterparse(io.BytesIO(head), events=("start",), recover=True):
            return el.tag
    except etree.XMLSyntaxError:
        return None
    return None


def _nth_newline(buf: bytearray, n: int) -> int:
    pos = -1
    for _ in range(n):
        pos = buf.find(b"\n", pos + 1)
    return pos + 1


def _turtle_cut(data: bytes) -> bytes:
    """Cut a Turtle sample after the last complete statement (a line ending in ' .')."""
    end = max(data.rfind(b" .\n"), data.rfind(b"\t.\n"))
    return data[:end + 3] if end > 0 else data


def run(cfg: Config) -> None:
    data = json.loads((cfg.raw / "distributions.json").read_text())
    groups, dists = data["groups"], data["distributions"]
    log(f"fetch: {len(groups)} groups")
    start = time.monotonic()
    results = asyncio.run(Fetcher(cfg).run(groups, dists))
    (cfg.raw / "sniff.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    counts = {}
    for r in results.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    log(f"  {counts} in {time.monotonic() - start:.0f}s")
