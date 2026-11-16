"""registry: seed the registry with the value domains that need no slot.

- Code lists: one value domain per LINDAS list and one per version (dcterms:isVersionOf the list),
  pointing at the LINDAS scheme (mdr:permissibleValues). From the cached code index.
- Identifiers: one per validator in identifiers.py.

Existing entries keep their IRIs; titles and versions follow LINDAS. Described value domains,
object classes, properties and the rest are created by the linking stages.
"""
import duckdb

from . import identifiers
from .config import Config
from .log import log
from .registry import COMPLETED, Registry, id_segment

LANGS = ("en", "de", "fr", "it")


def codelist_entries(reg: Registry, con) -> list[dict]:
    rows = con.execute("SELECT scheme, list, id, version, title_en, title_de, title_fr, title_it, "
                       "(SELECT COUNT(*) FROM codes c WHERE c.scheme = s.scheme AND c.kind = 'notation') FROM schemes s "
                       "ORDER BY id, version NULLS FIRST").fetchall()
    out = []
    for scheme, lst, ident, version, *titles, n in rows:
        title = {l: t for l, t in zip(LANGS, titles) if t} or {"en": ident}
        entry = {"kind": "codelist", "id": ident, "title": title, "status": COMPLETED, "nodeKind": "IRI",
                 "permissibleValues": scheme, "codes": n}
        if version:
            entry.update({"kind": "codelist-version", "id": f"{ident}/{version}", "version": version,
                          "iri": reg.iri("valuedomains", id_segment(ident), id_segment(version)),
                          "isVersionOf": reg.iri("valuedomains", id_segment(ident))})
        else:
            entry["iri"] = reg.iri("valuedomains", id_segment(ident))
        out.append(entry)
    return out


def identifier_entries(reg: Registry) -> list[dict]:
    out = []
    for v in identifiers.VALIDATORS:
        e = {"kind": "identifier", "id": f"identifier/{v.name}", "validator": v.name,
             "iri": reg.iri("valuedomains", "identifier", v.name), "title": v.title, "description": v.description,
             "status": COMPLETED, "datatype": v.datatype}
        if v.pattern:
            e["pattern"] = v.pattern
        if v.conforms_to:
            e["conformsTo"] = v.conforms_to
        out.append(e)
    return out


def check_wrappers(reg: Registry, con) -> list[str]:
    """Every code-list wrapper's permissible values resolve to a scheme fetched from LINDAS."""
    schemes = {r[0] for r in con.execute("SELECT scheme FROM schemes").fetchall()}
    return [e["iri"] for e in reg.all("valuedomains")
            if e.get("kind", "").startswith("codelist") and e["permissibleValues"] not in schemes]


def seed(reg: Registry, con) -> dict:
    counts = {"codelist": 0, "codelist-version": 0, "identifier": 0}
    for e in codelist_entries(reg, con) + identifier_entries(reg):
        reg.put("valuedomains", e)
        counts[e["kind"]] += 1
    return counts


def run(cfg: Config) -> None:
    reg = Registry.load(cfg.registry_dir, cfg.base_iri)
    if not cfg.codes_db.exists():
        raise SystemExit("registry: cache/codes.duckdb missing; run `python -m cmatch codes`")
    con = duckdb.connect(str(cfg.codes_db), read_only=True)
    try:
        counts = seed(reg, con)
        missing = check_wrappers(reg, con)
    finally:
        con.close()
    for iri in missing:      # never removed: links and confirmations may point at it
        reg.put("valuedomains", {**reg.get("valuedomains", iri), "status": "Deprecated"})
    if missing:
        log(f"registry: WARNING {len(missing)} code-list wrappers point at schemes no longer on LINDAS "
            f"(marked Deprecated), e.g. {missing[0]}")
    reg.save()
    log(f"registry: {counts}; {sum(len(v) for v in reg.entries.values())} entries in registry/")
