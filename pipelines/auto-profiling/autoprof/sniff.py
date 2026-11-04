"""Detect the format of a distribution from its first bytes.

Content rules come first because magic numbers don't cover what matters here
(CSV dialects, PX, JSON-LD, GML, PxWeb metadata, HTML error pages); libmagic
names whatever the rules leave unclassified.
"""
import csv
import re
import struct

import magic

from . import formats

HEAD_BYTES = 64 * 1024

PX_KEYWORDS = re.compile(rb"^\s*(CHARSET|AXIS-VERSION|LANGUAGE|LANGUAGES|CREATION-DATE|CODEPAGE|DECIMALS|"
                         rb"SHOWDECIMALS|MATRIX|SUBJECT-CODE|SUBJECT-AREA)\s*(\[[a-z]+\])?\s*=", re.M)
XML_ROOT = re.compile(r"<([A-Za-z_][\w.\-]*:)?([A-Za-z_][\w.\-]*)([^>]*)>", re.S)
NT_LINE = re.compile(r"^(<[^>]+>|_:\S+)\s+<[^>]+>\s+.+\.\s*$")
TURTLE = re.compile(r"^\s*(@prefix|@base|prefix\s+\w*:|base\s+<)", re.I | re.M)


def decode(head: bytes) -> str:
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
        if head.startswith(bom):
            return head[len(bom):].decode(enc, errors="replace")
    try:
        return head.decode("utf-8")
    except UnicodeDecodeError as e:
        if e.start > len(head) - 4:          # cut inside a multi-byte character
            return head[:e.start].decode("utf-8", errors="replace")
        return head.decode("cp1252", errors="replace")


def encoding(head: bytes) -> str:
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    try:
        head.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError as e:
        return "utf-8" if e.start > len(head) - 4 else "cp1252"


def zip_first_entry(head: bytes) -> str | None:
    if len(head) < 30:
        return None
    n = struct.unpack("<H", head[26:28])[0]
    return head[30:30 + n].decode("utf-8", errors="replace")


def ole_kind(head: bytes, detail: dict) -> str:
    """XLS if the OLE2 directory names an Excel workbook stream; OLE if not or out of reach."""
    if "excel" in detail.get("magic", ""):
        return "XLS"
    if len(head) >= 52:
        sector = 1 << struct.unpack("<H", head[30:32])[0]
        start = (struct.unpack("<I", head[48:52])[0] + 1) * sector
        directory = head[start:start + 4 * sector]
        if directory and ("Workbook".encode("utf-16-le") in directory or "Book".encode("utf-16-le") in directory):
            return "XLS"
    return "OLE"


def sniff(head: bytes, content_type: str | None = None) -> tuple[str | None, dict]:
    """→ (token, detail). token None means nothing recognisable."""
    detail = {}
    if not head:
        return None, {"reason": "empty"}
    try:
        detail["magic"] = magic.from_buffer(head[:HEAD_BYTES], mime=True)
    except magic.MagicException:
        pass

    if head.startswith(b"PAR1"):
        return "PARQUET", detail
    if head.startswith(b"SQLite format 3\x00"):
        app_id = head[68:72] if len(head) >= 72 else b""
        return ("GPKG", detail) if app_id in (b"GPKG", b"GP10", b"GP11") else ("SQLITE", detail)
    if head.startswith(b"PK\x03\x04"):
        first = zip_first_entry(head) or ""
        detail["firstEntry"] = first
        if first == "[Content_Types].xml" or first.startswith(("xl/", "_rels/", "docProps/")):
            # OOXML: a spreadsheet has xl/ parts; word/ or ppt/ ones are documents
            return ("XLSX", detail) if b"xl/" in head else ("OOXML", detail)
        if first == "mimetype":
            if b"opendocument.spreadsheet" in head[:200]:
                return "ODS", detail
            return "ODF", detail
        return "ZIP", detail
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return ole_kind(head, detail), detail
    for sig, token in ((b"%PDF", "PDF"), (b"\x89PNG", "PNG"), (b"\xff\xd8\xff", "JPEG"),
                       (b"II*\x00", "TIFF"), (b"MM\x00*", "TIFF"), (b"GIF8", "GIF"),
                       (b"\x1f\x8b", "GZIP"), (b"7z\xbc\xaf", "7Z")):
        if head.startswith(sig):
            return token, detail
    if PX_KEYWORDS.search(head[:4096]):
        return "PX", detail

    text = decode(head)
    stripped = text.lstrip()
    lowered = stripped[:2048].lower()

    first_line = next((l for l in stripped.splitlines() if l.strip() and not l.startswith("#")), "")
    if NT_LINE.match(first_line):
        return "NT", detail

    if stripped.startswith("<"):
        if "<!doctype html" in lowered or re.search(r"<html[\s>]", lowered) \
                or (lowered.startswith("<head") or lowered.startswith("<body")):
            return "HTML", detail
        return _xml(stripped, detail)

    if stripped.startswith(("{", "[")):
        return _json(stripped, detail)

    if TURTLE.search(stripped[:4096]):
        ct = (content_type or "").lower()
        return ("N3" if "n3" in ct else "RDF_TURTLE"), detail
    if dialect := csv_dialect(text):
        detail.update(dialect)
        return ("TSV" if dialect["delimiter"] == "\t" else "CSV"), detail

    mime = detail.get("magic", "")
    if mime.startswith("text/"):
        return "TXT", detail
    return formats.MEDIA_TYPES.get(mime) or "OCTET", detail


def _xml(text: str, detail: dict) -> tuple[str, dict]:
    body = re.sub(r"<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>", "", text[:HEAD_BYTES], flags=re.S).lstrip()
    m = XML_ROOT.match(body)
    if not m:
        return "XML", detail
    prefix, local, attrs = (m.group(1) or "")[:-1], m.group(2), m.group(3)
    detail["root"] = f"{prefix}:{local}" if prefix else local
    ns = dict(re.findall(r'xmlns(?::([\w.\-]+))?\s*=\s*"([^"]*)"', attrs))
    root_ns = ns.get(prefix, "")
    if root_ns:
        detail["rootNamespace"] = root_ns
    if local == "RDF" and "rdf-syntax-ns" in root_ns:
        return "RDF_XML", detail
    if local in ("WFS_Capabilities",) or root_ns.startswith("http://www.opengis.net/wfs"):
        if local == "FeatureCollection":
            return "GML", detail
        return "WFS", detail
    if "opengis.net/gml" in root_ns or (local == "FeatureCollection" and "opengis.net/gml" in attrs):
        return "GML", detail
    if local in ("kml",) or "opengis.net/kml" in root_ns:
        return "KML", detail
    if local == "gpx":
        return "GPX", detail
    if local in ("TRANSFER",) and "interlis" in root_ns.lower():
        return "INTERLIS", detail
    if m2 := re.search(r'schemaLocation\s*=\s*"([^"]+)"', attrs):
        detail["schemaLocation"] = m2.group(1)
    return "XML", detail


def _json(text: str, detail: dict) -> tuple[str, dict]:
    head = text[:HEAD_BYTES]
    if re.search(r'"@context"\s*:', head[:8192]):
        return "JSON_LD", detail
    if re.search(r'"type"\s*:\s*"(FeatureCollection|Feature)"', head[:8192]):
        return "GEOJSON", detail
    if '"variables"' in head and '"valueTexts"' in head:
        return "PXWEB", detail
    lines = [l for l in head.splitlines()[:6] if l.strip()]
    if len(lines) > 1 and all(l.strip().startswith("{") and l.rstrip().endswith("}") for l in lines[:-1]):
        return "JSONL", detail
    return "JSON", detail


def csv_dialect(text: str) -> dict | None:
    """A delimiter that splits the first lines into a constant number (≥2) of columns."""
    lines = [l for l in text.splitlines()[:60] if l.strip()]
    if len(lines) > 2:
        lines = lines[:-1]           # the last line may be cut off
    if len(lines) < 2:
        return None
    sample = "\n".join(lines)
    try:
        d = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = d.delimiter
    except csv.Error:
        counts = {c: [l.count(c) for l in lines] for c in ",;\t|"}
        stable = [c for c, n in counts.items() if n[0] > 0 and len(set(n)) == 1]
        if not stable:
            return None
        delimiter = max(stable, key=lambda c: counts[c][0])
    rows = list(csv.reader(lines, delimiter=delimiter))
    widths = [len(r) for r in rows]
    common = max(set(widths), key=widths.count)
    if common < 2 or widths.count(common) < 0.8 * len(widths):
        return None
    try:
        header = csv.Sniffer().has_header(sample)
    except csv.Error:
        header = True
    return {"delimiter": delimiter, "header": header}
