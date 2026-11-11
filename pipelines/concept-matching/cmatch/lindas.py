"""codes: the I14Y code lists on LINDAS → cache/codes.duckdb (the local code index).

LINDAS graph https://lindas.admin.ch/fso/i14y holds ~340 lists and ~390 versions as
skos:ConceptSchemes: a list (identity) at …/concept/{ID}, its versions at
…/concept/{ID}/version/{V}. Every scheme has its own codes (skos:inScheme, skos:notation,
xkos:level); together about 509k. They are matched locally, so only the wrappers go into
visoto-qlever.

Refreshed per list: a list is fetched again when the set of its schemes on LINDAS differs from
the cached one (a new version also changes the identity's codes); `--force` refetches all.
"""
import re
from concurrent.futures import ThreadPoolExecutor

import duckdb
import httpx

from . import bulk
from .config import Config
from .log import log

USER_AGENT = "visoto-pipelines/concept-matching"
CONCEPT = "https://register.ld.admin.ch/i14y/concept/"
LANGS = ("en", "de", "fr", "it")
SUFFIX = re.compile(r"\s*\((identity|version [^)]*)\)\s*$")

SCHEMES_QUERY = """
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX schema: <http://schema.org/>
PREFIX pav: <http://purl.org/pav/>
SELECT ?s (SAMPLE(?id0) AS ?id) (SAMPLE(?v0) AS ?version) (SAMPLE(?vf0) AS ?validFrom)
       (SAMPLE(?t_en) AS ?title_en) (SAMPLE(?t_de) AS ?title_de)
       (SAMPLE(?t_fr) AS ?title_fr) (SAMPLE(?t_it) AS ?title_it)
WHERE { GRAPH <%(graph)s> {
  ?s a skos:ConceptScheme .
  FILTER(STRSTARTS(STR(?s), "%(concept)s"))
  OPTIONAL { ?s schema:identifier ?id0 }
  OPTIONAL { ?s pav:version ?v0 }
  OPTIONAL { ?s schema:validFrom ?vf0 }
  OPTIONAL { ?s skos:prefLabel ?t_en FILTER(LANG(?t_en) = "en") }
  OPTIONAL { ?s skos:prefLabel ?t_de FILTER(LANG(?t_de) = "de") }
  OPTIONAL { ?s skos:prefLabel ?t_fr FILTER(LANG(?t_fr) = "fr") }
  OPTIONAL { ?s skos:prefLabel ?t_it FILTER(LANG(?t_it) = "it") }
} } GROUP BY ?s"""

CODES_QUERY = """
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xkos: <http://rdf-vocabulary.ddialliance.org/xkos#>
SELECT ?notation ?level WHERE {{ GRAPH <{graph}> {{
  ?c skos:inScheme <{scheme}> ; skos:notation ?notation .
  OPTIONAL {{ ?c xkos:level ?level }}
}} }}"""


def norm(value) -> str | None:
    """A value as compared with code notations: trimmed, integers without padding or '.0', upper case."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r"[+-]?\d+(\.0+)?", s):
        return str(int(float(s))) if len(s) < 16 else s.split(".")[0].lstrip("+").lstrip("0") or "0"
    return s.upper()


def level_identity(level: str | None) -> str | None:
    """A version's level IRI (…/level_4/version/2024.1.0) as the list's level (…/level_4)."""
    return re.sub(r"/version/.*$", "", level) if level else None


def split_scheme(iri: str) -> tuple[str, str, str | None]:
    """(list IRI, list identifier, version) of a scheme IRI."""
    m = re.fullmatch(re.escape(CONCEPT) + r"([^/]+)(?:/version/(.+))?", iri)
    if not m:
        raise ValueError(f"not an I14Y concept scheme: {iri}")
    return CONCEPT + m.group(1), m.group(1), m.group(2)


def connect(path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path))
    con.execute("""CREATE TABLE IF NOT EXISTS schemes (scheme VARCHAR PRIMARY KEY, list VARCHAR, id VARCHAR,
                   version VARCHAR, valid_from VARCHAR, title_en VARCHAR, title_de VARCHAR, title_fr VARCHAR,
                   title_it VARCHAR)""")
    con.execute("""CREATE TABLE IF NOT EXISTS codes (scheme VARCHAR, list VARCHAR, version VARCHAR,
                   level VARCHAR, notation VARCHAR, norm VARCHAR)""")
    return con


class Lindas:
    def __init__(self, endpoint: str, graph: str, timeout: float = 120):
        self.endpoint, self.graph = endpoint, graph
        self.http = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT,
                                                           "Accept": "application/sparql-results+json"})

    def select(self, query: str) -> list[dict]:
        for attempt in range(3):
            try:
                r = self.http.post(self.endpoint, data={"query": query})
                r.raise_for_status()
                return [{k: v["value"] for k, v in b.items()} for b in r.json()["results"]["bindings"]]
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt == 2:
                    raise
        return []

    def schemes(self) -> list[dict]:
        q = SCHEMES_QUERY % {"graph": self.graph, "concept": CONCEPT}
        rows = []
        for b in self.select(q):
            lst, ident, version = split_scheme(b["s"])
            rows.append({"scheme": b["s"], "list": lst, "id": b.get("id") or ident,
                         "version": version or None, "valid_from": b.get("validFrom"),
                         **{f"title_{l}": SUFFIX.sub("", b[f"title_{l}"]) if b.get(f"title_{l}") else None
                            for l in LANGS}})
        return rows

    def codes(self, scheme: str) -> list[tuple[str, str | None]]:
        return [(b["notation"], b.get("level")) for b in
                self.select(CODES_QUERY.format(graph=self.graph, scheme=scheme))]


def refresh(con, lindas: Lindas, force: bool = False, workers: int = 4) -> dict:
    remote = lindas.schemes()
    cached = {r[0] for r in con.execute("SELECT scheme FROM schemes").fetchall()}
    by_list: dict[str, set] = {}
    for r in remote:
        by_list.setdefault(r["list"], set()).add(r["scheme"])
    cached_by_list: dict[str, set] = {}
    for scheme, lst in con.execute("SELECT scheme, list FROM schemes").fetchall():
        cached_by_list.setdefault(lst, set()).add(scheme)
    stale = {lst for lst, s in by_list.items() if force or cached_by_list.get(lst) != s}
    gone = set(cached_by_list) - set(by_list)
    for lst in stale | gone:
        con.execute("DELETE FROM codes WHERE list = ?", [lst])
        con.execute("DELETE FROM schemes WHERE list = ?", [lst])
    todo = [r for r in remote if r["list"] in stale]
    for r in todo:
        con.execute("INSERT INTO schemes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [r["scheme"], r["list"], r["id"], r["version"], r["valid_from"],
                     r["title_en"], r["title_de"], r["title_fr"], r["title_it"]])
    rows = []
    with ThreadPoolExecutor(workers) as pool:
        for r, codes in zip(todo, pool.map(lambda r: lindas.codes(r["scheme"]), todo)):
            rows += [(r["scheme"], r["list"], r["version"], level_identity(level), n, norm(n)) for n, level in codes]
    bulk.insert(con, "codes", ["scheme", "list", "version", "level", "notation", "norm"], rows)
    return {"schemes": len(remote), "lists": len(by_list), "refetched_lists": len(stale), "removed_lists": len(gone),
            "unchanged": len(cached & {r["scheme"] for r in remote}) if not force else 0}


def run(cfg: Config, force: bool = False) -> None:
    cfg.cache.mkdir(parents=True, exist_ok=True)
    con = connect(cfg.codes_db)
    try:
        stats = refresh(con, Lindas(cfg["LINDAS_ENDPOINT"], cfg["I14Y_GRAPH"]), force)
        n = con.execute("SELECT COUNT(*) FROM codes").fetchall()[0][0]
    finally:
        con.close()
    log(f"codes: {stats}, {n} codes in {cfg.codes_db.relative_to(cfg.pipeline_dir)}")
