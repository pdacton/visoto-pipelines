"""resolve: datasets.txt → raw/distributions.json and raw/resolve-report.json."""
import json
import re
import time
from collections import Counter, defaultdict
from urllib.parse import unquote

import httpx

from . import formats
from .config import Config
from .log import log
from .model import structure_id

BATCH = 100
USER_AGENT = "visoto-pipelines/auto-profiling"

QUERY = """
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>
SELECT ?dataset ?dist ?download ?access ?format ?media ?title ?modified ?identifier WHERE {
  VALUES ?dataset { %s }
  ?dataset dcat:distribution ?dist .
  FILTER(isIRI(?dist))
  OPTIONAL { ?dist dcat:downloadURL ?download }
  OPTIONAL { ?dist dcat:accessURL ?access }
  OPTIONAL { ?dist dct:format ?format }
  OPTIONAL { ?dist dcat:mediaType ?media }
  OPTIONAL { ?dist dct:title ?title }
  OPTIONAL { ?dist dct:modified ?modified }
  OPTIONAL { ?dist dct:identifier ?identifier }
}
"""
KNOWN = """
PREFIX dcat: <http://www.w3.org/ns/dcat#>
SELECT DISTINCT ?dataset WHERE { VALUES ?dataset { %s } ?dataset a dcat:Dataset }
"""

# Opendatasoft publishes one table in many formats under .../exports/<format>.
OPENDATASOFT = re.compile(r"^(https?://[^/]+/api/(?:explore/)?v2(?:\.1)?/catalog/datasets/[^/]+)/exports/")
# Which member of an export group gets profiled
PREFERENCE = ["PARQUET", "PX", "CSV", "XLSX", "JSONL", "JSON", "XLS", "ODS", "GPKG", "SHP", "GML"]
RDF_PREFERENCE = ["RDF_TURTLE", "NT", "N3", "RDF_XML", "JSON_LD"]


def read_datasets(path) -> list[str]:
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        iri = line.split()[0].strip("<>")   # a trailing "# comment" is allowed
        if iri not in out:
            out.append(iri)
    return out


def sparql(client: httpx.Client, endpoint: str, query: str) -> list[dict]:
    for attempt in range(4):
        try:
            r = client.post(endpoint, data={"query": query},
                            headers={"Accept": "application/sparql-results+json"})
            r.raise_for_status()
            return [{k: v["value"] for k, v in b.items()} for b in r.json()["results"]["bindings"]]
        except (httpx.HTTPError, ValueError) as e:
            if attempt == 3:
                raise
            log(f"  SPARQL retry {attempt + 1}: {e}")
            time.sleep(2 ** attempt * 2)


def group_key(dist: dict) -> tuple:
    """Distributions with the same key are equivalent exports of one table."""
    url = dist["downloadURL"] or dist["accessURL"] or ""
    if api := formats.pxweb_api(url):
        # One PxWeb table, linked per language and as a BFS asset page
        table = re.sub(r"/api/v1/[a-z]{2}/", "/api/v1/*/", unquote(api))
        return (dist["dataset"], re.sub(r"(?<!:)//+", "/", table))
    if m := OPENDATASOFT.match(url):
        kind = "rdf" if set(dist["declared"]) & formats.RDF_TOKENS else "table"
        return (dist["dataset"], m.group(1), kind)
    return (dist["dataset"], dist["iri"])


def rank(dist: dict) -> tuple:
    declared = dist["declared"]
    order = RDF_PREFERENCE if set(declared) & formats.RDF_TOKENS else PREFERENCE
    best = min((order.index(t) for t in declared if t in order), default=len(order))
    in_scope = any(t in formats.IN_SCOPE for t in declared)
    return (not formats.worth_fetching(declared), not in_scope, best, dist["iri"])


def build_groups(dists: dict[str, dict]) -> list[dict]:
    by_key = defaultdict(list)
    for d in dists.values():
        by_key[group_key(d)].append(d)
    groups = []
    for members in by_key.values():
        members.sort(key=rank)
        rep = members[0]
        groups.append({
            "id": structure_id(rep["iri"]),
            "dataset": rep["dataset"],
            "representative": rep["iri"],
            "members": [m["iri"] for m in members],
            # fallbacks if the representative can't be fetched
            "candidates": [m["iri"] for m in members if formats.worth_fetching(m["declared"])][:3],
        })
    groups.sort(key=lambda g: (g["dataset"], g["id"]))
    return groups


def collect(rows: list[dict]) -> dict[str, dict]:
    dists = {}
    for r in rows:
        d = dists.setdefault(r["dist"], {
            "iri": r["dist"], "dataset": r["dataset"], "downloadURL": None, "accessURL": None,
            "formats": [], "mediaTypes": [], "title": None, "modified": None, "identifier": None,
        })
        for key, col in (("downloadURL", "download"), ("accessURL", "access"),
                         ("modified", "modified"), ("identifier", "identifier")):
            if r.get(col) and not d[key]:
                d[key] = r[col]
        if r.get("title") and not d["title"]:
            d["title"] = r["title"]
        for key, col in (("formats", "format"), ("mediaTypes", "media")):
            if r.get(col) and r[col] not in d[key]:
                d[key].append(r[col])
    for d in dists.values():
        urls = [u for u in (d["downloadURL"], d["accessURL"]) if u]
        d["declared"] = formats.declared_types(d["formats"], d["mediaTypes"], urls)
        d["url"] = urls[0] if urls else None
    return dists


def run(cfg: Config) -> None:
    datasets = read_datasets(cfg.pipeline_dir / cfg["DATASETS"])
    log(f"resolve: {len(datasets)} datasets from {cfg['DATASETS']}")
    rows, known = [], set()
    with httpx.Client(timeout=120, headers={"User-Agent": USER_AGENT}) as client:
        for i in range(0, len(datasets), BATCH):
            values = " ".join(f"<{d}>" for d in datasets[i:i + BATCH])
            rows += sparql(client, cfg["ODS_ENDPOINT"], QUERY % values)
            known |= {r["dataset"] for r in sparql(client, cfg["ODS_ENDPOINT"], KNOWN % values)}
    dists = collect(rows)
    groups = build_groups(dists)
    with_dists = {d["dataset"] for d in dists.values()}

    cfg.raw.mkdir(parents=True, exist_ok=True)
    (cfg.raw / "distributions.json").write_text(json.dumps(
        {"datasets": datasets, "distributions": dists, "groups": groups}, indent=1, ensure_ascii=False))
    report = {
        "datasets": len(datasets),
        "unknown": [d for d in datasets if d not in known],
        "withoutDistributions": [d for d in datasets if d in known and d not in with_dists],
        "distributions": len(dists),
        "groups": len(groups),
        "declaredTypes": dict(Counter("|".join(d["declared"]) or "-" for d in dists.values()).most_common()),
    }
    (cfg.raw / "resolve-report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    log(f"  {len(dists)} distributions in {len(groups)} groups; "
        f"{len(report['unknown'])} unknown datasets, {len(report['withoutDistributions'])} without distributions")
