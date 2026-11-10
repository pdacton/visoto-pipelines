"""sample: a representative subset of the datasets of the last run → datasets-sample.txt.

Reads the output of a run over a larger list (out/profiles, out/slots.jsonl, raw/distributions.json),
so run it before re-running on the sample; that run overwrites out/. Deterministic: candidates are
taken in the order of a hash of their IRI, so the same run gives the same sample.

Rules, in order:
1. Only datasets with a profiled structure and at most MAX_SLOTS slots (no single WFS service
   dominates).
2. At most PER_HOST datasets per publisher, approximated by the host of the representative
   distribution's URL.
3. Cases concept matching must handle get a minimum number of datasets (CASES).
4. Each engine gets a minimum number of datasets (ENGINES); a dataset counts for each of its engines.
5. The rest is filled up to SIZE in hash order.
"""
import argparse
import collections
import hashlib
import json
import re
from urllib.parse import urlparse

from .config import Config
from .log import log

SIZE = 100
MAX_SLOTS = 300
PER_HOST = 5
ENGINES = {"tabular": 35, "geo": 30, "px": 15, "rdf": 10, "tree": 10}
CASES = {  # case → minimum datasets that have it
    "municipality-code": 10, "canton-code": 6, "labels-not-codes": 6, "identifier": 6, "small-int-code": 10,
}
CANTONS = {"ZH", "BE", "LU", "UR", "SZ", "OW", "NW", "GL", "ZG", "FR", "SO", "BS", "BL", "SH", "AR", "AI", "SG",
           "GR", "AG", "TG", "TI", "VD", "VS", "NE", "GE", "JU"}
PLACE_NAMES = {"zürich", "zurich", "bern", "berne", "luzern", "lucerne", "uri", "schwyz", "obwalden", "nidwalden",
               "glarus", "zug", "freiburg", "fribourg", "solothurn", "basel-stadt", "basel-landschaft", "schaffhausen",
               "appenzell ausserrhoden", "appenzell innerrhoden", "st. gallen", "st.gallen", "graubünden",
               "grisons", "aargau", "thurgau", "ticino", "tessin", "vaud", "waadt", "valais", "wallis",
               "neuchâtel", "neuenburg", "genève", "geneve", "genf", "jura", "basel", "winterthur", "lausanne",
               "lugano", "biel/bienne", "chur", "aarau", "sion", "thun", "köniz", "uster", "emmen"}
MUNI_NAME = re.compile(r"(bfs|gde|gmd|gemeinde|commune|comune|ofs)")
LABEL_NAME = re.compile(r"(name|nom|bezeichnung|label|text)")
CANTON_NAME = re.compile(r"(^|_)(kanton|canton|cantone|kt|ktkz)(_|$)")
UID = re.compile(r"^CHE-?\d{3}\.?\d{3}\.?\d{3}")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def ints(sample: list[str]) -> list[int] | None:
    try:
        return [int(float(v)) for v in sample if float(v).is_integer()] if sample else None
    except ValueError:
        return None


def cases(slot: dict) -> set[str]:
    """The concept-matching cases a slot is an example of, from its name and value sample."""
    name, sample, out = norm(slot["name"]), slot["sample"], set()
    nums = ints(sample)
    if nums and len(nums) == len(sample):
        if MUNI_NAME.search(name) and not LABEL_NAME.search(name) and all(1 <= n <= 7000 for n in nums) \
                and len(nums) >= 3:
            out.add("municipality-code")
        if CANTON_NAME.search(name) and all(1 <= n <= 26 for n in nums):
            out.add("canton-code")
        if re.search(r"(^|_)(egid|ewid|edid)(_|$)", name) or (re.search(r"(^|_)(plz|npa|postleitzahl|zip)(_|$)", name)
                                                and all(1000 <= n <= 9999 for n in nums)):
            out.add("identifier")
        if slot["categorical"] and max(nums) < 100 and 2 <= len(set(nums)) <= 20:
            out.add("small-int-code")
    if sample and CANTON_NAME.search(name) and all(v.upper() in CANTONS for v in sample):
        out.add("canton-code")
    if sample and sum(1 for v in sample if UID.match(v)) >= 0.8 * len(sample):
        out.add("identifier")
    if sample and slot["type"] == "string" and sum(1 for v in sample if v.lower() in PLACE_NAMES) >= 3:
        out.add("labels-not-codes")
    return out


def rank(iri: str) -> str:
    return hashlib.sha256(iri.encode()).hexdigest()


def candidates(cfg: Config) -> dict:
    profiles = [json.loads(p.read_text()) for p in (cfg.out / "profiles").glob("*.json") if not p.name.startswith("_")]
    dists = json.loads((cfg.raw / "distributions.json").read_text())["distributions"]
    ds = collections.defaultdict(lambda: {"engines": set(), "slots": 0, "cases": set(), "hosts": set(), "names": set()})
    by_structure = {}
    for p in profiles:
        if p["status"] != "profiled":
            continue
        d = ds[p["dataset"]]
        d["engines"].add(p.get("engine"))
        url = dists.get(p["representative"], {}).get("url") or p.get("url") or ""
        d["hosts"].add(urlparse(url).hostname or "?")
        by_structure[f"{cfg.base_iri}structure/{p['id']}"] = p["dataset"]
    for line in open(cfg.out / "slots.jsonl", encoding="utf-8"):
        slot = json.loads(line)
        d = ds.get(by_structure.get(slot["structure"]))
        if d is None:
            continue
        d["slots"] += 1
        d["names"].add(norm(slot["name"]))
        d["cases"] |= cases(slot)
    return {k: v for k, v in ds.items() if 0 < v["slots"] <= MAX_SLOTS}


def select(ds: dict, size: int = SIZE) -> tuple[list[str], dict]:
    order = sorted(ds, key=rank)
    chosen, hosts, why = [], collections.Counter(), {}

    def take(iri: str, reason: str) -> bool:
        host = min(ds[iri]["hosts"])
        if iri in why or hosts[host] >= PER_HOST or len(chosen) >= size:
            return False
        chosen.append(iri)
        hosts[host] += 1
        why[iri] = reason
        return True

    def fill(minimum: int, has, reason: str) -> None:
        count = sum(1 for i in chosen if has(i))
        for iri in order:
            if count >= minimum:
                return
            if has(iri) and take(iri, reason):
                count += 1

    for case, minimum in CASES.items():
        fill(minimum, lambda i, c=case: c in ds[i]["cases"], f"case:{case}")
    for engine, minimum in ENGINES.items():
        fill(minimum, lambda i, e=engine: e in ds[i]["engines"], f"engine:{engine}")
    for iri in order:
        take(iri, "fill")
    return chosen, why


def summary(ds: dict, chosen: list[str]) -> list[str]:
    eng = collections.Counter(e for i in chosen for e in ds[i]["engines"])
    case = collections.Counter(c for i in chosen for c in ds[i]["cases"])
    names = collections.Counter(n for i in chosen for n in ds[i]["names"])
    shared = sum(1 for i in chosen if any(names[n] >= 3 for n in ds[i]["names"]))
    hosts = len({min(ds[i]["hosts"]) for i in chosen})
    return [f"{len(chosen)} datasets, {sum(ds[i]['slots'] for i in chosen)} slots, {hosts} publisher hosts",
            "engines: " + ", ".join(f"{k} {v}" for k, v in sorted(eng.items())),
            "cases: " + ", ".join(f"{k} {case[k]}" for k in CASES),
            f"datasets sharing a column name with at least two others: {shared}"]


def run(cfg: Config, out: str = "datasets-sample.txt", size: int = SIZE) -> None:
    ds = candidates(cfg)
    chosen, why = select(ds, size)
    lines = summary(ds, chosen)
    header = ["# Representative sample of datasets-large.txt for concept matching, made by",
              "# `uv run python -m autoprof sample` from the 500-dataset run (rules in autoprof/sample.py).",
              *(f"# {s}" for s in lines), ""]
    body = []
    for reason in sorted({why[i] for i in chosen}, key=lambda r: (not r.startswith("case"), r)):
        body += [f"# {reason}", *sorted(i for i in chosen if why[i] == reason), ""]
    (cfg.pipeline_dir / out).write_text("\n".join(header + body))
    log(f"sample: {out}: " + "; ".join(lines))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="datasets-sample.txt")
    ap.add_argument("--size", type=int, default=SIZE)
    a = ap.parse_args(argv)
    run(Config.load(), a.out, a.size)
