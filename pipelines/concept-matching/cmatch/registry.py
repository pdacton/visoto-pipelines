"""The metadata registry: state in registry/*.jsonl, published as Turtle.

Entries are only added or changed, never renumbered or removed: their IRIs are referenced by
links and by a person's confirmations. One file per kind, one entry per line, in the order the
entries were created (stable diffs).

| file | class | made by |
|---|---|---|
| valuedomains.jsonl | mdr:ValueDomain | code lists (from LINDAS), identifiers (by hand), described (by rule) |
| objectclasses.jsonl | mdr:ObjectClass | the concept step (phase 3) |
| properties.jsonl | mdr:Property | the concept step (phase 3) |
| dataelementconcepts.jsonl | mdr:DataElementConcept | rule: object class + property |
| dataelements.jsonl | mdr:DataElement | rule: data element concept + value domain |
"""
import datetime
import hashlib
import json
import re
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, SH, SKOS, XSD

MDR = Namespace("https://register.ld.admin.ch/mds/ontology/metadataregistry/")
ADMS = Namespace("http://www.w3.org/ns/adms#")
STATUS = Namespace("http://purl.org/adms/status/")
QUDT = Namespace("http://qudt.org/schema/qudt/")
DCAT_VERSION = URIRef("http://www.w3.org/ns/dcat#version")     # DCAT 3; not in rdflib's DCAT namespace

KINDS = {  # file stem → (rdf class, IRI path segment)
    "valuedomains": (MDR.ValueDomain, "valuedomain"),
    "objectclasses": (MDR.ObjectClass, "objectclass"),
    "properties": (MDR.Property, "property"),
    "dataelementconcepts": (MDR.DataElementConcept, "dataelementconcept"),
    "dataelements": (MDR.DataElement, "dataelement"),
}
COMPLETED, CANDIDATE = "Completed", "UnderDevelopment"
PROVENANCE = {"created", "generatedBy", "derivedFrom"}


def today() -> str:
    return datetime.date.today().isoformat()


def opaque_id(*parts: str) -> str:
    """Identifier of a created entry: opaque, so a changed label never changes the IRI."""
    return "c-" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:8]


def id_segment(entry_id: str) -> str:
    """An entry identifier as one IRI-safe segment (versions contain '/')."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", entry_id).strip("-")


class Registry:
    def __init__(self, directory: Path, base: str):
        self.dir = directory
        self.base = base
        self.entries: dict[str, dict[str, dict]] = {k: {} for k in KINDS}
        self.changed: set[str] = set()

    @classmethod
    def load(cls, directory: Path, base: str) -> "Registry":
        reg = cls(directory, base)
        for kind in KINDS:
            path = directory / f"{kind}.jsonl"
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        e = json.loads(line)
                        reg.entries[kind][e["iri"]] = e
        return reg

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        for kind in self.changed:
            lines = [json.dumps(e, ensure_ascii=False, sort_keys=True) for e in self.entries[kind].values()]
            (self.dir / f"{kind}.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        self.changed.clear()

    # --- access ---------------------------------------------------------------------

    def iri(self, kind: str, *segments: str) -> str:
        return self.base + "/".join([KINDS[kind][1], *segments])

    def get(self, kind: str, iri: str) -> dict | None:
        return self.entries[kind].get(iri)

    def all(self, kind: str) -> list[dict]:
        return list(self.entries[kind].values())

    def find(self, iri: str) -> tuple[str, dict] | None:
        for kind, entries in self.entries.items():
            if iri in entries:
                return kind, entries[iri]
        return None

    def put(self, kind: str, entry: dict) -> dict:
        """Add an entry, or update the fields of an existing one (its IRI and provenance stay)."""
        old = self.entries[kind].get(entry["iri"])
        if old is None:
            entry = {"created": today(), **entry}
            self.entries[kind][entry["iri"]] = entry
            self.changed.add(kind)
            return entry
        # provenance records the first creation: a later run never rewrites it
        merged = {**old, **{k: v for k, v in entry.items() if k not in PROVENANCE}}
        if merged != old:
            self.entries[kind][entry["iri"]] = merged
            self.changed.add(kind)
        return merged

    # --- Turtle ----------------------------------------------------------------------

    def graph(self) -> Graph:
        g = Graph()
        g.bind("mdr", MDR)
        g.bind("adms", ADMS)
        for kind, (cls, _) in KINDS.items():
            for e in self.entries[kind].values():
                self.entry_triples(g, cls, e)
        return g

    def entry_triples(self, g: Graph, cls: URIRef, e: dict) -> None:
        s = URIRef(e["iri"])
        g.add((s, RDF.type, cls))
        g.add((s, DCTERMS.identifier, Literal(e["id"])))
        for lang, text in (e.get("title") or {}).items():
            g.add((s, DCTERMS.title, Literal(text, lang=lang)))
        for lang, text in (e.get("description") or {}).items():
            g.add((s, DCTERMS.description, Literal(text, lang=lang)))
        g.add((s, DCTERMS.created, Literal(e["created"], datatype=XSD.date)))
        if e.get("modified"):
            g.add((s, DCTERMS.modified, Literal(e["modified"], datatype=XSD.date)))
        g.add((s, ADMS.status, STATUS[e.get("status", COMPLETED)]))
        for key, prop in (("generatedBy", PROV.wasGeneratedBy), ("isVersionOf", DCTERMS.isVersionOf),
                          ("objectClass", MDR.objectClass), ("property", MDR.property),
                          ("dataElementConcept", MDR.dataElementConcept), ("valueDomain", MDR.valueDomain),
                          ("datatype", SH.datatype), ("unit", QUDT.hasUnit), ("path", SH.path),
                          ("replacedBy", DCTERMS.isReplacedBy)):
            if e.get(key):
                g.add((s, prop, URIRef(e[key])))
        for key, prop in (("derivedFrom", PROV.wasDerivedFrom), ("closeMatch", SKOS.closeMatch),
                          ("conformsTo", DCTERMS.conformsTo)):
            for v in _list(e.get(key)):
                g.add((s, prop, URIRef(v)))
        if e.get("nodeKind"):
            g.add((s, SH.nodeKind, SH[e["nodeKind"]]))
        if e.get("pattern"):
            g.add((s, SH.pattern, Literal(e["pattern"])))
        if e.get("version"):
            g.add((s, DCAT_VERSION, Literal(e["version"])))
        if e.get("permissibleValues"):
            pv = URIRef(e["permissibleValues"])
            g.add((s, MDR.permissibleValues, pv))
            g.add((pv, RDF.type, SKOS.ConceptScheme))      # true on LINDAS; stated so the graph validates alone
        if cls == MDR.DataElement and e.get("valueDomain"):
            g.add((s, SH.node, URIRef(e["valueDomain"])))


def _list(v) -> list:
    return v if isinstance(v, list) else [v] if v else []
