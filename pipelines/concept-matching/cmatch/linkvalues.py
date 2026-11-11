"""link-values: slots → value domains (phase 2, no LLM) → out/links.jsonl.

Per fingerprint (the result applies to every slot that shares it):
1. code lists: the value sample against the local code index (codematch);
2. identifiers: validators (identifiers.py);
3. described: by rule from the slot's profile (described.py), per slot (CRS and unit live outside
   the fingerprint).
The automatic value-domain match is the first that applies: an unambiguous code list, an
identifier, the described value domain. A person's match (confirmations) wins over all of them and
is offered to every slot with the same fingerprint (`confirmed-elsewhere`). A person's code-list
match is re-checked against the current values (drift).
"""
import json
from collections import defaultdict

from . import confirm, described, identifiers
from . import slots as slotio
from .codematch import Thresholds, match_all, matchable
from .config import Config
from .lindas import norm
from .log import log
from .registry import COMPLETED, Registry, id_segment


def run_iri(cfg: Config) -> str:
    return f"{cfg.base_iri}run/concept-matching/{(cfg.out / 'run-id').read_text().strip()}"


def start_run(cfg: Config) -> str:
    import datetime
    cfg.out.mkdir(parents=True, exist_ok=True)
    (cfg.out / "run-id").write_text(datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    return run_iri(cfg)


def identifier_hits(slot: dict, min_rate: float) -> list[tuple[str, float]]:
    hits = []
    for v in identifiers.VALIDATORS:
        r = v.applies(slot["name"], slot.get("sample") or [], min_rate)
        if r is not None:
            hits.append((v.name, round(r, 4)))
    return sorted(hits, key=lambda h: -h[1])


def described_vd(reg: Registry, slot: dict) -> str | None:
    k = described.key(slot)
    if k is None:
        return None
    ident, fields = k
    iri = reg.iri("valuedomains", "described", id_segment(ident))
    reg.put("valuedomains", {"iri": iri, "id": f"described/{ident}", "kind": "described", "status": COMPLETED,
                             **fields})
    return iri


def link(cfg: Config, slots: list[dict], reg: Registry, confirmations: list[dict]) -> list[dict]:
    t = Thresholds.from_config(cfg)
    run = run_iri(cfg)
    groups = slotio.by_fingerprint(slots)
    samples = {fp: g[0]["sample"] for fp, g in groups.items() if matchable(g[0])}
    codes = match_all(cfg.codes_db, samples, t) if cfg.codes_db.exists() else {}
    vd_of_scheme = {e["permissibleValues"]: e["iri"] for e in reg.all("valuedomains") if e.get("permissibleValues")}
    persons = defaultdict(list)          # slot IRI → placed confirmations
    elsewhere = defaultdict(list)        # fingerprint → placed value-domain confirmations
    for c in confirmations:
        if c["status"] == "placed":
            persons[c["slot"]].append(c)
            if c["kind"] == "valueDomain":
                elsewhere[c["fingerprint"]].append(c)
    rescored = _drift_scores(cfg, persons, slots, reg)
    min_rate = cfg.float("ID_MIN_RATE")
    out = []
    for fp, group in groups.items():
        res = codes.get(fp)
        ids = identifier_hits(group[0], min_rate)
        for slot in group:
            rec = {"slot": slot["iri"], "fingerprint": fp, "candidates": [], "matches": [], "notes": []}
            cands = rec["candidates"]
            if res:
                for rank, h in enumerate(res.candidates, start=1):
                    vd = vd_of_scheme.get(h.scheme)
                    if vd:
                        cands.append({"entry": vd, "kind": "valueDomain", "rank": rank, "score": h.containment,
                                      "evidence": {"method": "code-overlap", "containment": h.containment,
                                                   "coverage": h.coverage, "level": h.level},
                                      "run": run})
                if res.reason:
                    rec["codeReason"] = res.reason
            for name, rate in ids:
                cands.append({"entry": reg.iri("valuedomains", "identifier", name), "kind": "valueDomain",
                              "rank": len(cands) + 1, "score": rate,
                              "evidence": {"method": "id-validator"}, "run": run})
            dvd = described_vd(reg, slot)
            if dvd:
                cands.append({"entry": dvd, "kind": "valueDomain", "rank": len(cands) + 1, "score": 1.0,
                              "evidence": {"method": "rule"}, "run": run})
            for c in elsewhere.get(fp, []):
                if c["slot"] != slot["iri"]:
                    cands.append({"entry": c["entry"], "kind": "valueDomain", "rank": 1, "score": 1.0,
                                  "evidence": {"method": "confirmed-elsewhere"}, "run": run})
            # automatic value-domain match: code list, identifier, described
            auto = None
            if res and res.automatic and vd_of_scheme.get(res.automatic.scheme):
                h = res.automatic
                auto = {"entry": vd_of_scheme[h.scheme], "score": h.containment,
                        "evidence": {"method": "code-overlap", "containment": h.containment, "coverage": h.coverage,
                                     "level": h.level}}
            elif ids:
                auto = {"entry": reg.iri("valuedomains", "identifier", ids[0][0]), "score": ids[0][1],
                        "evidence": {"method": "id-validator"}}
            elif dvd:
                auto = {"entry": dvd, "score": 1.0, "evidence": {"method": "rule"}}
            mine = [c for c in persons.get(slot["iri"], []) if c["kind"] == "valueDomain"]
            if mine:
                c = mine[-1]
                rec["matches"].append(person_match(c))
                rec["valueDomain"] = c["entry"]
                d = rescored.get((slot["iri"], c["entry"]))
                if d is not None and d + 1e-9 < t.candidate_min:
                    rec["notes"].append({"drift": c["entry"], "containment": round(d, 4)})
            elif auto:
                rec["matches"].append({"entry": auto["entry"], "kind": "valueDomain", "matchType": "exactMatch",
                                       "score": auto["score"], "by": run, "evidence": auto["evidence"]})
                rec["valueDomain"] = auto["entry"]
            for c in persons.get(slot["iri"], []):          # concept and data element matches of a person
                if c["kind"] != "valueDomain":
                    rec["matches"].append(person_match(c))
            out.append(rec)
    return out


def person_match(c: dict) -> dict:
    return {"entry": c["entry"], "kind": c["kind"], "matchType": c["matchType"], "by": c["who"],
            "when": c["when"], "person": True}


def _drift_scores(cfg: Config, persons: dict, slots: list[dict], reg: Registry) -> dict:
    """(slot, entry) → containment of the slot's current values in a person's code-list entry."""
    import duckdb
    pairs = []
    by_iri = {s["iri"]: s for s in slots}
    for iri, cs in persons.items():
        for c in cs:
            e = reg.get("valuedomains", c["entry"]) if c["kind"] == "valueDomain" else None
            if e and e.get("permissibleValues") and by_iri[iri].get("sample"):
                pairs.append((iri, c["entry"], e["permissibleValues"], by_iri[iri]["sample"]))
    if not pairs or not cfg.codes_db.exists():
        return {}
    con = duckdb.connect(str(cfg.codes_db), read_only=True)
    try:
        out = {}
        for iri, entry, scheme, sample in pairs:
            values = {norm(v) for v in sample} - {None}
            codes = {r[0] for r in con.execute("SELECT DISTINCT norm FROM codes WHERE scheme = ?", [scheme]).fetchall()}
            out[(iri, entry)] = len(values & codes) / len(values) if values else 0.0
        return out
    finally:
        con.close()


def write(cfg: Config, links: list[dict]) -> None:
    with open(cfg.out / "links.jsonl", "w", encoding="utf-8") as f:
        for rec in links:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read(cfg: Config) -> list[dict]:
    with open(cfg.out / "links.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run(cfg: Config) -> None:
    start_run(cfg)
    reg = Registry.load(cfg.registry_dir, cfg.base_iri)
    slots = slotio.load(slotio.input_path(cfg))
    links = link(cfg, slots, reg, confirm.load(cfg))
    reg.save()
    write(cfg, links)
    methods = defaultdict(int)
    for rec in links:
        for m in rec["matches"]:
            if m["kind"] == "valueDomain":
                methods["person" if m.get("person") else m["evidence"]["method"]] += 1
    log(f"link-values: {len(links)} slots, {len(slotio.by_fingerprint(slots))} fingerprints; "
        f"value-domain matches {dict(methods)}; without {sum(1 for r in links if not r.get('valueDomain'))}")
