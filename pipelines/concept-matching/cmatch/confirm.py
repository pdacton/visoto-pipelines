"""confirm: confirmations.csv (a person's matches) → out/confirmations.json and out/<name>-confirmations.ttl.

Until a review UI exists, a person's matches are rows in confirmations.csv, keyed by the slot's
re-attach key (dataset, distributions, container path, source name), never by its IRI: slot IRIs
change when a structure's representative distribution changes. Every run re-attaches each row to
the current slot whose dataset, container and source name are the same and whose structure
shares a distribution. Rows that cannot be placed, or fit several slots, are reported.

The Turtle goes into its own graph (CONFIRMATIONS_GRAPH), which pipeline runs never replace.
"""
import csv
import datetime
import json
import re

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import PROV, RDF, SKOS, XSD

from . import slots as slotio
from .config import Config
from .log import log
from .registry import Registry

AP = Namespace("https://register.ld.admin.ch/mds/ontology/ap/")
MATCH_TYPES = {"exactMatch", "closeMatch", "broadMatch", "narrowMatch", "relatedMatch"}
KIND_OF = {"valuedomains": "valueDomain", "dataelementconcepts": "dataElementConcept", "dataelements": "dataElement"}
COLUMNS = ["re_attach_dataset", "re_attach_distributions", "re_attach_container", "re_attach_source_name",
           "entry", "match_type", "who", "when", "note"]


def person_iri(who: str) -> str:
    who = who.strip()
    if re.match(r"^(https?|urn|mailto):", who):
        return who
    if "@" in who:
        return "mailto:" + who
    return "urn:visoto:person:" + (re.sub(r"[^a-z0-9]+", "-", who.lower()).strip("-") or "unknown")


def timestamp(when: str) -> str:
    when = (when or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
        return when + "T00:00:00Z"
    try:
        datetime.datetime.fromisoformat(when.replace("Z", "+00:00"))
        return when
    except ValueError:
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_rows(path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if (r.get("entry") or "").strip()]


def place(rows: list[dict], slots: list[dict], reg: Registry) -> list[dict]:
    index: dict[tuple, list[dict]] = {}
    for s in slots:
        index.setdefault(slotio.key_of(s), []).append(s)
    out = []
    for i, r in enumerate(rows, start=2):           # line number in the CSV
        dists = set((r.get("re_attach_distributions") or "").split())
        key = (r["re_attach_dataset"].strip(), r["re_attach_container"].strip(), r["re_attach_source_name"].strip())
        found = [s for s in index.get(key, []) if not dists or dists & set(s["key"]["distributions"])]
        entry = r["entry"].strip()
        hit = reg.find(entry)
        mt = (r.get("match_type") or "exactMatch").strip().removeprefix("skos:")
        c = {"line": i, "key": {"dataset": key[0], "distributions": sorted(dists), "container": key[1],
                                "sourceName": key[2]},
             "entry": entry, "matchType": mt if mt in MATCH_TYPES else "exactMatch",
             "who": person_iri(r.get("who") or ""), "when": timestamp(r.get("when") or ""),
             "note": (r.get("note") or "").strip()}
        if hit is None or hit[0] not in KIND_OF:
            c["status"] = "unknown-entry"
        elif not found:
            c["status"] = "unplaced"
        elif len(found) > 1:
            c["status"], c["slots"] = "ambiguous", [s["iri"] for s in found]
        else:
            c.update(status="placed", slot=found[0]["iri"], fingerprint=found[0]["fingerprint"], kind=KIND_OF[hit[0]])
        out.append(c)
    return out


def graph(confirmations: list[dict]) -> Graph:
    g = Graph()
    g.bind("ap", AP)
    for c in confirmations:
        if c["status"] != "placed":
            continue
        m = BNode()
        g.add((URIRef(c["slot"]), AP.match, m))
        g.add((m, RDF.type, AP.Match))
        g.add((m, AP.concept, URIRef(c["entry"])))
        g.add((m, AP.matchType, SKOS[c["matchType"]]))
        g.add((m, PROV.wasAttributedTo, URIRef(c["who"])))
        g.add((m, PROV.generatedAtTime, Literal(c["when"], datatype=XSD.dateTime)))
        k = c["key"]
        g.add((m, AP.keyDataset, URIRef(k["dataset"])))
        for d in k["distributions"] or []:
            g.add((m, AP.keyDistribution, URIRef(d)))
        g.add((m, AP.keyContainer, Literal(k["container"])))
        g.add((m, AP.keySourceName, Literal(k["sourceName"])))
    return g


def load(cfg: Config) -> list[dict]:
    path = cfg.out / "confirmations.json"
    return json.loads(path.read_text()) if path.exists() else []


def run(cfg: Config) -> None:
    reg = Registry.load(cfg.registry_dir, cfg.base_iri)
    slots = slotio.load(slotio.input_path(cfg))
    confirmations = place(read_rows(cfg.pipeline_dir / "confirmations.csv"), slots, reg)
    # A person's match needs its full key in the graph: fill in the slot's distributions when the row omitted them
    by_iri = {s["iri"]: s for s in slots}
    for c in confirmations:
        if c["status"] == "placed" and not c["key"]["distributions"]:
            c["key"]["distributions"] = by_iri[c["slot"]]["key"]["distributions"]
    cfg.out.mkdir(parents=True, exist_ok=True)
    (cfg.out / "confirmations.json").write_text(json.dumps(confirmations, indent=1, ensure_ascii=False))
    graph(confirmations).serialize(cfg.out / f"{cfg['NAME']}-confirmations.ttl", format="turtle")
    counts = {}
    for c in confirmations:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    log(f"confirm: {len(confirmations)} rows {counts}")
