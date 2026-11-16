"""emit: registry/*.jsonl and out/links.jsonl → out/parts/*.nt (graph GRAPH, replaced on every run).

- 00-vocab.nt: the ap: and mdr: vocabularies, so visoto can label the terms;
- 10-registry.nt: every registry entry;
- 20-links.nt: candidates with evidence, automatic matches, the shortcuts (ap:valueDomain,
  ap:dataElementConcept, ap:dataElement) and ap:mainObjectClass of containers; the run.
A person's matches are not here but in <name>-confirmations.ttl (their own graph); the shortcuts
they win are.
"""
import json

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import PROV, RDF, RDFS, SKOS, XSD

from . import linkvalues
from .config import Config
from .log import log
from .registry import Registry

AP = Namespace("https://register.ld.admin.ch/mds/ontology/ap/")
SHORTCUTS = {"valueDomain": AP.valueDomain, "dataElementConcept": AP.dataElementConcept,
             "dataElement": AP.dataElement}


def evidence(g: Graph, node, ev: dict) -> None:
    e = BNode()
    g.add((node, AP.evidence, e))
    g.add((e, RDF.type, AP.Evidence))
    g.add((e, AP.method, Literal(ev["method"])))
    for key in ("containment", "coverage"):
        if ev.get(key) is not None:
            g.add((e, AP[key], Literal(round(float(ev[key]), 4), datatype=XSD.decimal)))
    if ev.get("level"):
        g.add((e, AP.level, URIRef(ev["level"])))
    if ev.get("matched"):
        g.add((e, AP.matchedOn, Literal(ev["matched"])))
    for lang in ev.get("languages") or []:
        g.add((e, AP.labelLanguage, Literal(lang)))
    if ev.get("rationale"):
        g.add((e, AP.rationale, Literal(ev["rationale"])))


def links_graph(links: list[dict], run: str, main_classes: dict) -> Graph:
    g = Graph()
    g.bind("ap", AP)
    R = URIRef(run)
    g.add((R, RDF.type, PROV.Activity))
    g.add((R, RDFS.label, Literal(f"concept-matching run {run.rsplit('/', 1)[-1]}")))
    for rec in links:
        S = URIRef(rec["slot"])
        for c in rec["candidates"]:
            n = BNode()
            g.add((S, AP.candidate, n))
            g.add((n, RDF.type, AP.Candidate))
            g.add((n, AP.concept, URIRef(c["entry"])))
            g.add((n, AP.candidateRank, Literal(int(c["rank"]))))
            g.add((n, AP.candidateScore, Literal(round(float(c["score"]), 4), datatype=XSD.decimal)))
            g.add((n, PROV.wasGeneratedBy, R))
            evidence(g, n, c["evidence"])
        for m in rec["matches"]:
            if m.get("person"):
                continue                      # in the confirmations graph
            n = BNode()
            g.add((S, AP.match, n))
            g.add((n, RDF.type, AP.Match))
            g.add((n, AP.concept, URIRef(m["entry"])))
            g.add((n, AP.matchType, SKOS[m.get("matchType", "exactMatch")]))
            if m.get("score") is not None:
                g.add((n, AP.candidateScore, Literal(round(float(m["score"]), 4), datatype=XSD.decimal)))
            g.add((n, PROV.wasAttributedTo, URIRef(m["by"])))
            if m.get("evidence"):
                evidence(g, n, m["evidence"])
        for key, prop in SHORTCUTS.items():
            if rec.get(key):
                g.add((S, prop, URIRef(rec[key])))
    for container, oc in main_classes.items():
        g.add((URIRef(container), AP.mainObjectClass, URIRef(oc)))
    return g


def vocab_graph(cfg: Config) -> Graph:
    g = Graph()
    for f in ("ap.ttl", "mdr.ttl"):
        g.parse(cfg.pipeline_dir / "vocab" / f, format="turtle")
    return g


def run(cfg: Config) -> None:
    parts = cfg.out / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    reg = Registry.load(cfg.registry_dir, cfg.base_iri)
    links = linkvalues.read(cfg)
    mc_path = cfg.out / "main-object-classes.json"
    main_classes = json.loads(mc_path.read_text()) if mc_path.exists() else {}
    vocab_graph(cfg).serialize(parts / "00-vocab.nt", format="nt", encoding="utf-8")
    reg.graph().serialize(parts / "10-registry.nt", format="nt", encoding="utf-8")
    g = links_graph(links, linkvalues.run_iri(cfg), main_classes)
    g.serialize(parts / "20-links.nt", format="nt", encoding="utf-8")
    log(f"emit: {sum(len(v) for v in reg.entries.values())} registry entries, {len(links)} slots, {len(g)} link triples")
