"""emit: out/profiles/*.json → out/parts/*.nt (SHACL structures, profiles, provenance) and out/slots.jsonl.

Output vocabulary is ap: (metadata-swiss/mds-datamodel ontology/autoprofiling, copied to vocab/ap.ttl).
Structure and profile stay apart: constraints describe the data (sh:datatype,
sh:in, cardinality), observed statistics hang off each slot via ap:observed and
never become constraints. See .project/auto-profiling/02-model.md.

out/slots.jsonl is not part of the graph: one line per slot with its value sample and
fingerprint, the input of the concept-matching pipeline.
"""
import hashlib
import json
import logging
import re
from decimal import Decimal
from pathlib import Path

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import DCAT, DCTERMS, PROV, RDF, RDFS, SH, SKOS, XSD

from . import formats
from .config import Config
from .log import log
from .model import NUMERIC, TEMPORAL, Field, Part, Structure, slug, unique_slugs

AP = Namespace("https://register.ld.admin.ch/mds/ontology/ap/")
RML = Namespace("http://w3id.org/rml/")
CUBE = Namespace("https://cube.link/")
INT64_MIN, INT64_MAX = -2**63, 2**63 - 1
SDO = Namespace("http://schema.org/")          # as LINDAS cubes use it, not rdflib's https
META = Namespace("https://cube.link/meta/")
QUDT = Namespace("http://qudt.org/schema/qudt/")
CSVW = Namespace("http://www.w3.org/ns/csvw#")
TIME = Namespace("http://www.w3.org/2006/time#")
GEO_WKT = URIRef("http://www.opengis.net/ont/geosparql#wktLiteral")
EPSG = "http://www.opengis.net/def/crs/EPSG/0/"
logging.getLogger("rdflib.term").setLevel(logging.ERROR)   # ill-typed literals are handled in literal()
NEIGHBOURS = 5      # slot names on each side written to slots.jsonl as context

TYPES = {  # Table Schema type → (sh:datatype, qudt scale type of a measure)
    "string": (XSD.string, QUDT.NominalScale), "integer": (XSD.integer, QUDT.RatioScale),
    "number": (XSD.decimal, QUDT.RatioScale), "boolean": (XSD.boolean, QUDT.NominalScale),
    "date": (XSD.date, QUDT.IntervalScale), "datetime": (XSD.dateTime, QUDT.IntervalScale),
    "time": (XSD.time, QUDT.IntervalScale), "year": (XSD.gYear, QUDT.IntervalScale),
    "yearmonth": (XSD.gYearMonth, QUDT.IntervalScale), "duration": (XSD.duration, QUDT.RatioScale),
    "geojson": (GEO_WKT, None), "geopoint": (GEO_WKT, None),
}
CONSTRAINTS = {"minimum": SH.minInclusive, "maximum": SH.maxInclusive, "exclusiveMinimum": SH.minExclusive,
               "exclusiveMaximum": SH.maxExclusive, "minLength": SH.minLength, "maxLength": SH.maxLength,
               "pattern": SH.pattern}
TIME_UNITS = {"date": "unitDay", "datetime": "unitSecond", "year": "unitYear", "yearmonth": "unitMonth",
              "day": "unitDay", "month": "unitMonth"}
STAT_INTS = {"count", "distinct", "maxItems", "maxPerInstance"}
STAT_KEYS = ["count", "nullPercentage", "distinct", "min", "max", "mean", "std", "q25", "q50", "q75",
             "support", "maxItems", "maxPerInstance"]
STAT_TERMS = {"min": "minValue", "max": "maxValue"}     # profile JSON key → ap: local name where they differ
# Engines whose cardinalities are observed; tabular fields are single-valued by construction
EXPLICIT_CARDINALITY = {"tree", "rdf"}


class Emitter:
    def __init__(self, base: str, run_iri: URIRef):
        self.base = base
        self.run = run_iri
        self.slots: list[dict] = []      # slots.jsonl records of the structures emitted so far
        self._ctx: dict = {}

    def graph(self) -> Graph:
        g = Graph()
        for p, ns in [("sh", SH), ("xsd", XSD), ("cube", CUBE), ("meta", META), ("schema", SDO), ("qudt", QUDT),
                      ("csvw", CSVW), ("ap", AP), ("rml", RML), ("dct", DCTERMS), ("dcat", DCAT), ("prov", PROV),
                      ("skos", SKOS), ("time", TIME)]:
            g.bind(p, ns, override=True, replace=True)
        return g

    def structure_iri(self, sid: str) -> URIRef:
        return URIRef(f"{self.base}structure/{sid}")

    # --- structure --------------------------------------------------------------

    def structure(self, s: Structure, dists: dict) -> Graph:
        g = self.graph()
        S = self.structure_iri(s.id)
        g.add((S, RDF.type, AP.DataStructure))
        g.add((S, DCTERMS.identifier, Literal(s.id)))
        g.add((S, AP.status, AP[s.status]))
        if s.statusReason:
            g.add((S, AP.statusReason, Literal(s.statusReason)))
        g.add((S, PROV.wasGeneratedBy, self.run))
        rep_iri = URIRef(s.representative)
        g.add((S, AP.profiledDistribution, rep_iri))
        rep = dists.get(s.representative, {})
        if rep.get("title"):
            g.add((S, RDFS.label, Literal(rep["title"])))
        for key, prop in (("downloadURL", DCAT.downloadURL), ("accessURL", DCAT.accessURL)):
            if absolute(rep.get(key)):
                g.add((rep_iri, prop, URIRef(rep[key])))
        for token in s.declared:
            g.add((S, AP.declaredFormat, self.format_term(token)))
        sniffed = s.sniffed
        if sniffed:
            g.add((S, DCTERMS["format"], self.format_term(sniffed)))
        if s.formatMatch is not None:
            g.add((S, AP.formatMatch, Literal(bool(s.formatMatch))))
        if s.engine:
            g.add((S, AP.engine, Literal(s.engine)))
        for iri in s.distributions:
            D = URIRef(iri)
            g.add((D, RDF.type, DCAT.Distribution))
            g.add((D, DCTERMS.conformsTo, S))
            g.add((URIRef(dists.get(iri, {}).get("dataset", s.dataset)), DCAT.distribution, D))
        self._ctx = {"structure": S, "dataset": s.dataset, "distributions": sorted(s.distributions),
                     "engine": s.engine}
        for part in s.parts:
            N = URIRef(f"{S}/{part.slug}")
            g.add((S, DCTERMS.hasPart, N))
            self.part(g, part, N, f"{N}/col/", s.engine)
            self.logical_source(g, part, N, rep_iri)
        return g

    def format_term(self, token: str):
        iri = formats.eu_iri(token)
        return URIRef(iri) if iri else Literal(token)

    # --- part (node shape) ---------------------------------------------------------

    def part(self, g: Graph, part: Part, N: URIRef, col_base: str, engine: str | None) -> None:
        g.add((N, RDF.type, SH.NodeShape))
        g.add((N, RDF.type, AP.Container))
        if part.label:
            g.add((N, RDFS.label, Literal(part.label)))
        if part.rowCount is not None:
            g.add((N, AP.rowCount, Literal(int(part.rowCount))))
        if part.targetClass and absolute(part.targetClass):
            g.add((N, SH.targetClass, absolute(part.targetClass)))
        if part.geometryType:
            g.add((N, AP.geometryType, Literal(part.geometryType)))
        if part.crs:
            g.add((N, AP.crs, URIRef(EPSG + part.crs)))
        cube = part.is_cube()
        if cube:
            g.add((N, RDF.type, CUBE.Constraint))
            g.add((N, SH.closed, Literal(True)))
            for path, node in [(RDF.type, CUBE.Observation), (CUBE.observedBy, None)]:
                ps = BNode()
                g.add((N, SH.property, ps))
                g.add((ps, SH.path, path))
                g.add((ps, SH.nodeKind, SH.IRI))
                if node:
                    self.in_list(g, ps, [node])
        keys = part.key_fields() if cube else []
        names = [f.name for f in part.fields]
        for order, (f, fslug) in enumerate(zip(part.fields, unique_slugs(names))):
            F = URIRef(f"{N}/{fslug}")
            g.add((N, SH.property, F))
            dtype = self.field(g, f, F, order, col_base + fslug, engine, part, cube, f in keys)
            record = self.slot_record(f, F, dtype, N, part, names, order)
            g.add((F, AP.fingerprint, Literal(record["fingerprint"])))
            self.slots.append(record)

    # --- physical description (rml:LogicalSource) -------------------------------------

    def logical_source(self, g: Graph, part: Part, N: URIRef, distribution: URIRef) -> None:
        """How a top-level container is read from the representative distribution."""
        L = URIRef(f"{N}/source")
        g.add((L, RDF.type, RML.LogicalSource))
        g.add((L, AP.container, N))
        g.add((L, RML.source, distribution))
        if part.tableName:
            g.add((L, AP.tableName, Literal(str(part.tableName))))
        d = part.dialect or {}
        if d.get("recordsPath"):
            g.add((L, RML.referenceFormulation, RML.JSONPath))
            g.add((L, RML.iterator, Literal(json_path(d["recordsPath"]))))
        elif d.get("delimiter"):
            g.add((L, RML.referenceFormulation, RML.CSV))
        if any(k in d for k in ("delimiter", "encoding", "header", "skipRows", "headerRowCount")):
            self.dialect(g, L, d)

    def dialect(self, g: Graph, L: URIRef, d: dict) -> None:
        node = BNode()
        g.add((L, CSVW.dialect, node))
        for key, prop in (("delimiter", CSVW.delimiter), ("encoding", CSVW.encoding)):
            if d.get(key) is not None:
                g.add((node, prop, Literal(d[key])))
        if "header" in d:
            g.add((node, CSVW.header, Literal(bool(d["header"]))))
        for key, prop in (("skipRows", CSVW.skipRows), ("headerRowCount", CSVW.headerRowCount)):
            if d.get(key) is not None:
                g.add((node, prop, Literal(int(d[key]))))

    # --- field (property shape) ------------------------------------------------------

    def field(self, g: Graph, f: Field, F: URIRef, order: int, col: str, engine: str | None,
              part: Part, cube: bool, is_key: bool):
        """The slot's triples; returns its sh:datatype (or None)."""
        name = f.title or f.name
        g.add((F, RDF.type, SH.PropertyShape))
        g.add((F, RDF.type, AP.Slot))
        g.add((F, SH.name, Literal(name)))
        g.add((F, SDO.name, Literal(name)))
        if f.title and f.title != f.name:
            g.add((F, AP.sourceName, Literal(f.name)))
        g.add((F, SH.order, Literal(order)))
        g.add((F, SH.path, absolute(f.path) or URIRef(col)))
        if f.description:
            g.add((F, SH.description, Literal(f.description)))

        dtype = URIRef(f.datatype) if f.datatype else TYPES.get(f.type, (None, None))[0]
        if f.node is not None and f.type == "object":
            dtype = None
        if dtype:
            g.add((F, SH.datatype, dtype))
        if f.nodeKind:
            g.add((F, SH.nodeKind, URIRef(f.nodeKind)))
        if f.cls and absolute(f.cls):
            g.add((F, SH["class"], absolute(f.cls)))
        if f.format:
            g.add((F, AP["format"], Literal(f.format)))

        c = f.constraints
        if engine in EXPLICIT_CARDINALITY or f.minCount is not None:
            min_count = f.minCount or 0
        else:
            nulls = f.stats.get("nullPercentage")
            required = c.get("required") or f.name in part.primaryKey or (nulls == 0 and f.stats.get("count"))
            min_count = 1 if required else 0
        g.add((F, SH.minCount, Literal(min_count)))
        max_count = f.maxCount if engine in EXPLICIT_CARDINALITY else (f.maxCount if f.maxCount is not None else 1)
        if max_count is not None:
            g.add((F, SH.maxCount, Literal(max_count)))
        for key, prop in CONSTRAINTS.items():
            if key in c:
                g.add((F, prop, self.literal(c[key], dtype if prop != SH.pattern else None)))
        codes = c.get("enum") or (f.stats.get("values") if f.categorical else None)
        if codes and dtype != GEO_WKT:
            if f.nodeKind == str(SH.IRI):
                items = [absolute(v) for v in codes]
                if all(items):          # e.g. "<->" in a publisher's N3 parses as a relative IRI
                    self.in_list(g, F, items)
            else:
                self.in_list(g, F, [self.literal(v, dtype) for v in codes])
        if f.categorical:
            g.add((F, AP.categorical, Literal(True)))
        if f.booleanCandidate:
            g.add((F, AP.booleanCandidate, Literal(True)))
        for code, labels in f.codeLabels.items():
            node = BNode()
            g.add((F, AP.codeLabel, node))
            g.add((node, SKOS.notation, Literal(code)))
            for lang, label in labels.items():
                g.add((node, SKOS.prefLabel, Literal(label, lang=lang)))
        if f.unitLabel:
            g.add((F, AP.unitLabel, Literal(f.unitLabel)))

        if cube:
            self.cube_dimension(g, f, F, is_key)
        elif f.unit:
            g.add((F, QUDT.unit, URIRef(f.unit)))

        if f.node is not None:
            node_iri = URIRef(f"{F}/node")
            g.add((F, SH.node, node_iri))
            self.part(g, f.node, node_iri, col + "/", engine)

        self.observed(g, F, f, dtype)
        return dtype

    def cube_dimension(self, g: Graph, f: Field, F: URIRef, is_key: bool) -> None:
        g.add((F, RDF.type, CUBE.KeyDimension if is_key else CUBE.MeasureDimension))
        scale = TYPES.get(f.type, (None, None))[1]
        temporal = f.type in TEMPORAL or f.stats.get("isTime")
        if is_key:
            scale = QUDT.IntervalScale if temporal else QUDT.NominalScale
        if scale:
            g.add((F, QUDT.scaleType, scale))
        if temporal:
            unit = TIME_UNITS.get(f.type if f.type in TEMPORAL else (f.format or f.stats.get("timeUnit") or ""))
            kind = BNode()
            g.add((F, META.dataKind, kind))
            g.add((kind, RDF.type, TIME.GeneralDateTimeDescription))
            if unit:
                g.add((kind, TIME.unitType, TIME[unit]))
        if f.unit:
            g.add((F, QUDT.unit, URIRef(f.unit)))

    def observed(self, g: Graph, F: URIRef, f: Field, dtype) -> None:
        stats = {k: f.stats[k] for k in STAT_KEYS if f.stats.get(k) is not None}
        if not stats and not f.examples:
            return
        node = BNode()
        g.add((F, AP.observed, node))
        g.add((node, RDF.type, AP.Observation))
        g.add((node, PROV.wasGeneratedBy, self.run))
        for k, v in stats.items():
            if k in STAT_INTS:
                lit = Literal(int(v))
            elif k in ("nullPercentage", "support", "mean", "std"):
                lit = Literal(Decimal(str(round(float(v), 4))))
            else:          # min, max, quartiles: in the field's own type where valid
                lit = self.literal(v, dtype if f.type in NUMERIC | TEMPORAL else None)
            g.add((node, AP[STAT_TERMS.get(k, k)], lit))
        for e in f.examples:
            g.add((node, AP.example, Literal(e)))

    # --- slots.jsonl ------------------------------------------------------------------

    def slot_record(self, f: Field, F: URIRef, dtype, N: URIRef, part: Part, names: list[str],
                    order: int) -> dict:
        """One line of out/slots.jsonl: what concept matching needs to know about a slot."""
        S = self._ctx["structure"]
        container = str(N)[len(str(S)) + 1:]
        datatype = str(dtype) if dtype else None
        return {
            "iri": str(F),
            # re-attach key: survives a change of the slot IRI (new representative distribution)
            "key": {"dataset": self._ctx["dataset"], "distributions": self._ctx["distributions"],
                    "container": container, "sourceName": f.name},
            "structure": str(S), "engine": self._ctx["engine"],
            "name": f.name, "label": f.title, "description": f.description,
            "container": {"iri": str(N), "path": container, "label": part.label,
                          "tableName": part.tableName, "slots": len(names),
                          "geometryType": part.geometryType, "crs": part.crs},
            "neighbours": names[max(0, order - NEIGHBOURS):order] + names[order + 1:order + 1 + NEIGHBOURS],
            "type": f.type, "datatype": datatype, "nested": f.node is not None,
            "unit": f.unit, "unitLabel": f.unitLabel, "format": f.format,
            "min": f.stats.get("min"), "max": f.stats.get("max"), "distinct": f.stats.get("distinct"),
            "count": f.stats.get("count"), "nullPercentage": f.stats.get("nullPercentage"),
            "categorical": f.categorical,
            "sample": f.sample,
            "fingerprint": fingerprint(f.name, datatype, f.sample),
        }

    # --- helpers ---

    def literal(self, value, dtype) -> Literal:
        if dtype in (None, XSD.string):
            return Literal(str(value), datatype=XSD.string) if dtype == XSD.string else Literal(str(value))
        if dtype in (XSD.integer, XSD.decimal):
            if not _numeric(value):
                return Literal(str(value))
            f = float(value)
            if dtype == XSD.integer and f.is_integer():
                n = value if isinstance(value, int) else int(f)
                if INT64_MIN <= n <= INT64_MAX:
                    return Literal(str(n), datatype=XSD.integer)
                # QLever stores integers as 64-bit and rejects larger ones; a decimal it can store
                return Literal(Decimal(n))
            # a non-integral statistic of an integer field (mean, quartile) is a decimal
            text = str(value) if isinstance(value, str) and "e" not in value.lower() else repr(f)
            return Literal(Decimal(text))
        lit = Literal(str(value) if not isinstance(value, bool) else str(value).lower(), datatype=dtype)
        return Literal(str(value)) if getattr(lit, "ill_typed", False) else lit

    def in_list(self, g: Graph, subject, items: list) -> None:
        head = BNode()
        Collection(g, head, items)
        g.add((subject, SH["in"], head))

    def run_graph(self, info: dict) -> Graph:
        g = self.graph()
        g.add((self.run, RDF.type, PROV.Activity))
        g.add((self.run, RDFS.label, Literal(f"auto-profiling run {info['id']}")))
        g.add((self.run, PROV.startedAtTime, Literal(info["started"], datatype=XSD.dateTime)))
        g.add((self.run, PROV.endedAtTime, Literal(info["ended"], datatype=XSD.dateTime)))
        g.add((self.run, AP.sampleRows, Literal(int(info["sampleRows"]))))
        for tool, v in sorted(info.get("tools", {}).items()):
            g.add((self.run, AP.toolVersion, Literal(f"{tool} {v}")))
        return g


def absolute(v) -> URIRef | None:
    """An IRI from the data, only if absolute; N-Triples and Jena reject relative ones."""
    return URIRef(v) if v and re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:\S+$", str(v)) else None


def _numeric(v) -> bool:
    try:
        float(v)
        return not isinstance(v, bool)
    except (TypeError, ValueError):
        return False


def json_path(pointer: str) -> str:
    """The records path (JSON Pointer of the array, "/" for the root) as an rml:iterator in JSONPath."""
    steps = [s.replace("~1", "/").replace("~0", "~") for s in pointer.strip("/").split("/") if s]
    path = "$" + "".join(f".{s}" if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s)
                         else "['" + s.replace("\\", "\\\\").replace("'", "\\'") + "']" for s in steps)
    return path + "[*]"


def fingerprint(name: str, datatype: str | None, sample: list[str]) -> str:
    """Hash of the normalised name, datatype and value sample: slots that share it are matched once."""
    norm = re.sub(r"[^a-z0-9]+", "_", slug(name)).strip("_")      # case, accents and separators folded
    data = json.dumps([norm, datatype or "", sorted(sample)], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def vocab_graph(path: Path) -> Graph:
    """vocab/ap.ttl, shipped in the output so visoto can label the terms."""
    return Graph().parse(path, format="turtle")


def run(cfg: Config) -> None:
    profiles = cfg.out / "profiles"
    parts = cfg.out / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    info = json.loads((profiles / "_run.json").read_text())
    dists = json.loads((cfg.raw / "distributions.json").read_text())["distributions"]
    em = Emitter(cfg.base_iri, URIRef(f"{cfg.base_iri}run/{info['id']}"))
    vocab_graph(cfg.pipeline_dir / "vocab" / "ap.ttl").serialize(parts / "00-vocab.nt", format="nt", encoding="utf-8")
    em.run_graph(info).serialize(parts / "00-run.nt", format="nt", encoding="utf-8")
    counts = {}
    with open(cfg.out / "slots.jsonl", "w", encoding="utf-8") as slots:
        for path in sorted(profiles.glob("*.json")):
            if path.name.startswith("_"):
                continue
            s = Structure.read(path)
            em.structure(s, dists).serialize(parts / f"{s.id}.nt", format="nt", encoding="utf-8")
            for record in em.slots:
                slots.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            em.slots.clear()
            counts[s.status] = counts.get(s.status, 0) + 1
    log(f"emit: {sum(counts.values())} structures {counts} → {parts.relative_to(cfg.pipeline_dir)}, out/slots.jsonl")
