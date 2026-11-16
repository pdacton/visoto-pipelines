"""report: out/report.md — links, review queue, confirmations, drift, gold sets, registry."""
import csv
import json
from collections import Counter, defaultdict

from . import confirm, linkvalues
from . import slots as slotio
from .config import Config
from .log import log
from .registry import Registry

REVIEW_ROWS = 50


def table(headers: list[str], rows: list[list]) -> str:
    def cell(v):
        return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    return "\n".join(lines + ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows])


def title(reg: Registry, iri: str | None) -> str:
    if not iri:
        return ""
    hit = reg.find(iri)
    if not hit:
        return iri
    e = hit[1]
    return f"{e['id']} ({(e.get('title') or {}).get('en') or next(iter((e.get('title') or {}).values()), '')})"


def method_of(m: dict) -> str:
    return "person" if m.get("person") else m["evidence"]["method"]


# --- gold sets --------------------------------------------------------------------------

def read_csv(path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if not (r.get("dataset") or "").startswith("#")]


def slot_by_key(slots: list[dict]) -> dict[tuple, list[dict]]:
    out = defaultdict(list)
    for s in slots:
        out[slotio.key_of(s)].append(s)
    return out


def gold_values(rows: list[dict], slots: list[dict], links: dict, reg: Registry) -> dict:
    """Precision and recall of the automatic code-list and identifier links on gold-values.csv.

    expected: a registry identifier (e.g. DV_KT_BEZ_GDE_SNAP, identifier/egid) for slots that should
    get that code-list or identifier value domain, `described` for slots that should get only their
    described value domain, `none` for slots that should get no value domain. A code-list version
    counts as its list. A key that matches several slots with one fingerprint (the same column in two
    structures of a dataset) is evaluated once."""
    idx = slot_by_key(slots)
    tp = fp = fn = 0
    missing, errors = [], []
    for r in rows:
        key = (r["dataset"], r["container"], r["source_name"])
        found = idx.get(key, [])
        # one slot, or the same column in several structures of the dataset (one fingerprint, one result)
        if not found or len({s["fingerprint"] for s in found}) != 1:
            missing.append(key)
            continue
        rec = links[found[0]["iri"]]
        got = None
        for m in rec["matches"]:
            if m["kind"] == "valueDomain" and not m.get("person") and method_of(m) in ("code-overlap", "id-validator", "llm"):
                e = reg.get("valuedomains", m["entry"]) or {}
                got = e["id"].split("/")[0] if e.get("kind") == "codelist-version" else e.get("id")
        expected = r["expected"].strip()
        enumerated = expected not in ("described", "none", "")
        if got and enumerated and got == expected:
            tp += 1
        else:
            if got:
                fp += 1
                errors.append((key, expected, got))
            if enumerated:
                fn += 1
                if not got:
                    errors.append((key, expected, "-"))
    p = tp / (tp + fp) if tp + fp else None
    rec_ = tp / (tp + fn) if tp + fn else None
    return {"rows": len(rows), "evaluated": len(rows) - len(missing), "missing": missing, "tp": tp, "fp": fp,
            "fn": fn, "precision": p, "recall": rec_, "errors": errors}


def gold_pairs(rows: list[dict], slots: list[dict], links: dict) -> dict:
    """Precision and recall of shared data element concepts on gold-pairs.csv (same: 1 or 0)."""
    idx = slot_by_key(slots)
    tp = fp = fn = 0
    missing = []
    for r in rows:
        a = idx.get((r["dataset"], r["container"], r["source_name"]), [])
        b = idx.get((r["dataset_2"], r["container_2"], r["source_name_2"]), [])
        if len(a) != 1 or len(b) != 1:
            missing.append(r)
            continue
        da, db = links[a[0]["iri"]].get("dataElementConcept"), links[b[0]["iri"]].get("dataElementConcept")
        same_pred = bool(da and da == db)
        same = r["same"].strip() == "1"
        tp += same and same_pred
        fp += (not same) and same_pred
        fn += same and not same_pred
    return {"rows": len(rows), "missing": len(missing), "tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None}


def pct(v) -> str:
    return "–" if v is None else f"{v:.2f}"


# --- the report ---------------------------------------------------------------------------

def build(cfg: Config) -> tuple[str, dict]:
    reg = Registry.load(cfg.registry_dir, cfg.base_iri)
    slots = slotio.load(slotio.input_path(cfg))
    links = {r["slot"]: r for r in linkvalues.read(cfg)}
    by_iri = {s["iri"]: s for s in slots}
    groups = slotio.by_fingerprint(slots)
    confirmations = confirm.load(cfg)
    out = ["# concept-matching report", "",
           f"Run `{(cfg.out / 'run-id').read_text().strip()}`; {len(slots)} slots, {len(groups)} fingerprints, "
           f"concept model `{cfg['CONCEPT_MODEL']}`.", ""]

    # links
    kinds = Counter()
    for r in links.values():
        for m in r["matches"]:
            kinds[(m["kind"], method_of(m))] += 1
    shortcuts = {k: sum(1 for r in links.values() if r.get(k)) for k in ("valueDomain", "dataElementConcept", "dataElement")}
    out += ["## Links", "", table(["kind", "method", "slots"], [[k, m, n] for (k, m), n in sorted(kinds.items())]), "",
            table(["shortcut", "slots"], [[k, n] for k, n in shortcuts.items()]), "",
            "Code lists, why no automatic link (per slot):", "",
            table(["reason", "slots"], [[k or "linked", n] for k, n in
                                       Counter(r.get("codeReason") for r in links.values()).most_common()])]

    # what code-list links matched, and value domains shared across datasets
    matched = Counter()
    for r in links.values():
        for m in r["matches"]:
            if m["kind"] == "valueDomain" and (m.get("evidence") or {}).get("matched"):
                matched[(m["evidence"]["matched"], ", ".join(m["evidence"].get("languages") or []))] += 1
    out += ["", "Code-list links by what the values matched:", "",
            table(["matched", "label languages", "slots"], [[k, l, n] for (k, l), n in sorted(matched.items())])
            if matched else "None."]
    shared = defaultdict(set)
    for r in links.values():
        e = reg.get("valuedomains", r.get("valueDomain") or "")
        if e and e.get("pattern") and e.get("kind") == "described":
            shared[e["iri"]].add(by_iri[r["slot"]]["key"]["dataset"])
    rows = sorted(([reg.get("valuedomains", iri)["pattern"], len(ds)] for iri, ds in shared.items() if len(ds) > 1),
                  key=lambda x: (-x[1], x[0]))
    out += ["", f"### Pattern value domains ({len(shared)}, {len(rows)} shared by more than one dataset)", "",
            table(["pattern", "datasets"], rows) if rows else "None shared."]

    # review queue: one row per fingerprint with code-list candidates but no automatic code-list link
    queue = []
    for fp, group in groups.items():
        r = links[group[0]["iri"]]
        codes = [c for c in r["candidates"] if c["evidence"]["method"] == "code-overlap"]
        linked = any(m["kind"] == "valueDomain" and method_of(m) in ("code-overlap", "person", "llm") for m in r["matches"])
        if codes and not linked:
            s = group[0]
            queue.append((len(group), s["name"], r.get("codeReason"), ", ".join(sorted({x.get("label") or "" for x in
                          [g.get("container") or {} for g in group]}))[:60],
                          "; ".join(f"{title(reg, c['entry'])[:50]} {c['evidence']['containment']}" for c in codes),
                          ", ".join((s.get("sample") or [])[:6])[:60]))
    queue.sort(key=lambda q: (-q[0], q[1]))
    out += ["", f"## Review queue ({len(queue)} fingerprints, top {REVIEW_ROWS})", "",
            "Fingerprints with code-list candidates but no accepted code-list link, by the number of slots they cover.",
            "", table(["slots", "name", "reason", "containers", "candidates (containment)", "sample"],
                      [list(q) for q in queue[:REVIEW_ROWS]])]

    # confirmations and drift
    status = Counter(c["status"] for c in confirmations)
    drift = [(by_iri[r["slot"]]["name"], title(reg, n["drift"]), n["containment"]) for r in links.values()
             for n in r["notes"] if "drift" in n]
    out += ["", "## Confirmations", "", table(["status", "rows"], [[k, v] for k, v in sorted(status.items())]) if status
            else "No rows in confirmations.csv."]
    problems = [c for c in confirmations if c["status"] != "placed"]
    if problems:
        out += ["", table(["line", "status", "dataset", "container", "source name", "entry"],
                          [[c["line"], c["status"], c["key"]["dataset"], c["key"]["container"], c["key"]["sourceName"],
                            c["entry"]] for c in problems])]
    out += ["", "### Drift", "", "A person's code-list match whose slot's current values no longer fit the list.", "",
            table(["slot", "entry", "containment"], drift) if drift else "None."]

    # gold sets
    gv = gold_values(read_csv(cfg.pipeline_dir / "tests" / "gold-values.csv"), slots, links, reg)
    gp = gold_pairs(read_csv(cfg.pipeline_dir / "tests" / "gold-pairs.csv"), slots, links)
    out += ["", "## Gold sets", "",
            table(["set", "rows", "evaluated", "precision", "recall", "tp", "fp", "fn"],
                  [["values (automatic code-list and identifier links)", gv["rows"], gv["evaluated"],
                    pct(gv["precision"]), pct(gv["recall"]), gv["tp"], gv["fp"], gv["fn"]],
                   ["pairs (shared data element concept)", gp["rows"], gp["rows"] - gp["missing"],
                    pct(gp["precision"]), pct(gp["recall"]), gp["tp"], gp["fp"], gp["fn"]]])]
    if gv["errors"]:
        out += ["", table(["slot (dataset, container, source name)", "expected", "got"],
                          [[" / ".join(k), e, g] for k, e, g in gv["errors"][:40]])]
    if gv["missing"]:
        out += ["", f"{len(gv['missing'])} gold-value rows match no current slot (or several)."]

    # registry
    use = Counter(r[k] for r in links.values() for k in ("valueDomain", "dataElementConcept", "dataElement") if r.get(k))
    by_kind = Counter((kind, e.get("kind", ""), e.get("status", "Completed")) for kind in reg.entries
                      for e in reg.entries[kind].values())
    used = [(iri, n) for iri, n in use.most_common()]
    out += ["", "## Registry", "", table(["kind", "sub-kind", "status", "entries"],
                                          [[k, s, st, n] for (k, s, st), n in sorted(by_kind.items())]),
            "", f"Entries linked from at least one slot: {len(use)}; from a single slot: "
                f"{sum(1 for _, n in used if n == 1)}.", "", "Most used:", "",
            table(["entry", "slots"], [[title(reg, iri), n] for iri, n in used[:20]])]
    return "\n".join(out) + "\n", {"gold_values": gv, "gold_pairs": gp}


def run(cfg: Config) -> None:
    text, stats = build(cfg)
    (cfg.out / "report.md").write_text(text)
    gv = stats["gold_values"]
    log(f"report: out/report.md (gold values precision {pct(gv['precision'])}, recall {pct(gv['recall'])})")
