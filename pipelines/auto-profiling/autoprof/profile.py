"""profile: raw/samples/* → out/profiles/{id}.json, one Structure per group."""
import json
import os
import shutil
import time
import traceback
import zipfile
from concurrent.futures import as_completed
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from pebble import ProcessPool

from . import formats
from .config import Config
from .engines import EngineError, NotTabular
from .log import log
from .model import Structure

WORKERS = min(4, os.cpu_count() or 1)
TOOLS = ["duckdb", "frictionless", "rdflib", "shexer", "genson", "lxml", "pyaxis", "pyogrio"]


def tool_versions() -> dict:
    out = {}
    for t in TOOLS:
        try:
            out[t] = version(t)
        except Exception:  # noqa: BLE001
            pass
    try:
        import pyogrio
        out["gdal"] = pyogrio.__gdal_version_string__
    except Exception:  # noqa: BLE001
        pass
    return out


def extract(sample: Path, member: str, tmp: Path) -> Path:
    """A ZIP member (with its sidecar files for shapefiles) unpacked into tmp."""
    with zipfile.ZipFile(sample) as z:
        stem = member.rsplit(".", 1)[0]
        for name in z.namelist():
            if name == member or name.rsplit(".", 1)[0] == stem:
                z.extract(name, tmp)
    return tmp / member


def engine_for(token: str) -> str | None:
    if token in ("JSON", "JSONL"):
        return "tabular"   # falls back to tree when the JSON holds no records
    if token == "TXT":
        return "tabular"
    return formats.family(token)


def run_engine(cfg: Config, token: str, path: Path, detail: dict, tmp: Path) -> tuple[str, list]:
    engine = engine_for(token)
    if engine == "tabular":
        from .engines import tabular
        try:
            return "tabular", tabular.profile(path, token, cfg, tmp, detail)
        except NotTabular:
            if token != "JSON":
                raise EngineError("not-tabular")
            engine = "tree"
    if engine == "tree":
        from .engines import tree
        return "tree", tree.profile(path, token, cfg, tmp, detail)
    if engine == "geo":
        from .engines import geo
        return "geo", geo.profile(path, token, cfg, tmp, detail)
    if engine == "px":
        from .engines import px
        return "px", px.profile(path, token, cfg, tmp, detail)
    if engine == "rdf":
        from .engines import rdf
        return "rdf", rdf.profile(path, token, cfg, tmp, detail)
    raise EngineError(f"no-engine:{token}")


def profile_group(pipeline_dir: str, group: dict, sniffed: dict) -> dict:
    """Runs in a worker process; returns the Structure as a dict."""
    cfg = Config.load(Path(pipeline_dir))
    s = Structure(id=group["id"], dataset=group["dataset"], representative=group["representative"],
                  distributions=group["members"], url=sniffed.get("url"), declared=sniffed.get("declared", []),
                  sniffed=sniffed.get("sniffed"), formatMatch=sniffed.get("match"))
    if sniffed.get("status") != "ok":
        s.status, s.statusReason = sniffed.get("status", "failed"), sniffed.get("reason")
        return json.loads(s.to_json())
    start = time.monotonic()
    tmp = cfg.out / "tmp" / group["id"]
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        path = cfg.pipeline_dir / sniffed["sample"]
        token, detail = sniffed["sniffed"], dict(sniffed.get("detail") or {})
        if token == "ZIP":
            token, member = detail["inner"], detail["member"]
            if token == "SHP":
                path = f"/vsizip/{path}/{member}"      # a str: Path() would collapse GDAL's "//"
            else:
                path = extract(path, member, tmp)
            if token in ("CSV", "TSV"):
                from .sniff import encoding
                detail["encoding"] = encoding(path.read_bytes()[:65536])
        s.engine, s.parts = run_engine(cfg, token, path, detail, tmp)
        if not s.parts:
            s.status, s.statusReason = "failed", "no-parts"
    except EngineError as e:
        s.status, s.statusReason = "failed", str(e)
    except Exception as e:  # noqa: BLE001 - one bad sample must not stop the run
        s.status, s.statusReason = "failed", f"error:{type(e).__name__}:{e}"[:300]
        (tmp / "traceback.txt").write_text(traceback.format_exc())
    finally:
        s.seconds = round(time.monotonic() - start, 2)
    return json.loads(s.to_json())


def run(cfg: Config, only: set | None = None) -> None:
    data = json.loads((cfg.raw / "distributions.json").read_text())
    sniffed = json.loads((cfg.raw / "sniff.json").read_text())
    groups = [g for g in data["groups"] if not only or g["id"] in only]
    out = cfg.out / "profiles"
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(cfg.out / "tmp", ignore_errors=True)
    started = datetime.now(timezone.utc)
    limit = cfg.int("PROFILE_TIMEOUT")
    log(f"profile: {len(groups)} groups, {WORKERS} workers, {limit}s per group")
    counts = {}
    # pebble rather than ProcessPoolExecutor: an overrunning group's worker is killed and replaced.
    with ProcessPool(WORKERS) as pool:
        futures = {pool.schedule(profile_group, args=(str(cfg.pipeline_dir), g, sniffed.get(g["id"], {})),
                                 timeout=limit): g
                   for g in groups}
        for fut in as_completed(futures):
            g = futures[fut]
            try:
                d = fut.result()
            except Exception as e:  # noqa: BLE001 - an overrunning or crashed worker
                reason = f"timeout:{limit}s" if isinstance(e, TimeoutError) else f"worker:{type(e).__name__}"
                d = json.loads(Structure(id=g["id"], dataset=g["dataset"], representative=g["representative"],
                                         distributions=g["members"], status="failed",
                                         statusReason=reason).to_json())
            (out / f"{g['id']}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False))
            counts[d["status"]] = counts.get(d["status"], 0) + 1
            parts = d.get("parts", [])
            if d["status"] != "skipped":
                log(f"  {g['id']} {d['status']:8} {d.get('engine') or '-':7} {len(parts)} parts "
                    f"{sum(len(p.get('fields', [])) for p in parts)} fields {d.get('seconds', 0)}s "
                    f"{d.get('statusReason') or ''}"[:200])
    run_info = {"started": started.isoformat(), "ended": datetime.now(timezone.utc).isoformat(),
                "id": started.strftime("%Y%m%dT%H%M%SZ"), "sampleRows": cfg.int("SAMPLE_ROWS"),
                "tools": tool_versions()}
    (out / "_run.json").write_text(json.dumps(run_info, indent=1))
    log(f"  {counts}")
