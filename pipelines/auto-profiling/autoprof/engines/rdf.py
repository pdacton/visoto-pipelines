"""RDF engine: JSON-LD, Turtle, N3, N-Triples, RDF/XML → shapes per class (sheXer).

sheXer infers one shape per class; its output is read back into model Parts and
its constraints are completed with the observed support ratio (share of the
class's instances using the property) and value statistics from rdflib.
"""
from collections import Counter
from pathlib import Path

import rdflib
from rdflib import RDF, SH, Literal, URIRef

from ..model import CATEGORICAL_MAX, Field, Part, truncate_examples, unique_slugs
from . import EngineError

FORMATS = {"RDF_TURTLE": "turtle", "N3": "n3", "NT": "nt", "RDF_XML": "xml", "JSON_LD": "json-ld"}
SH_DATATYPE_TYPO = URIRef(str(SH) + "dataType")       # what sheXer writes
XSD = "http://www.w3.org/2001/XMLSchema#"
XSD_TO_TS = {"string": "string", "integer": "integer", "int": "integer", "long": "integer", "decimal": "number",
             "double": "number", "float": "number", "boolean": "boolean", "date": "date",
             "dateTime": "datetime", "time": "time", "gYear": "year", "gYearMonth": "yearmonth",
             "duration": "duration"}
MAX_CLASSES = 50


def parse(path: Path, token: str, cap: int) -> rdflib.Graph:
    data = path.read_bytes()
    fmt = FORMATS[token]
    for fraction in (1.0, 0.9, 0.75, 0.5):      # a truncated sample may end mid-statement
        chunk = data if fraction == 1.0 else _cut(data, int(len(data) * fraction))
        g = rdflib.Graph()
        try:
            g.parse(data=chunk, format=fmt)
            break
        except Exception as e:  # noqa: BLE001 - rdflib raises many types
            error = e
            if token in ("RDF_XML", "JSON_LD"):
                raise EngineError(f"rdf-parse:{str(error).splitlines()[0][:100]}")
    else:
        raise EngineError(f"rdf-parse:{str(error).splitlines()[0][:100]}")
    if len(g) > cap:
        small = rdflib.Graph()
        for s in dict.fromkeys(g.subjects()):
            for t in g.triples((s, None, None)):
                small.add(t)
            if len(small) >= cap:
                break
        g = small
    return g


def _cut(data: bytes, size: int) -> bytes:
    end = max(data.rfind(b" .\n", 0, size), data.rfind(b"\t.\n", 0, size))
    return data[:end + 3] if end > 0 else data[:size]


def shexer_shapes(g: rdflib.Graph) -> rdflib.Graph:
    from shexer.consts import SHACL_TURTLE, TURTLE
    from shexer.shaper import Shaper
    shaper = Shaper(rdflib_graph=g, all_classes_mode=True, input_format=TURTLE, disable_comments=True)
    out = rdflib.Graph()
    out.parse(data=shaper.shex_graph(string_output=True, output_format=SHACL_TURTLE, acceptance_threshold=0),
              format="turtle")
    return out


def local_name(iri: str) -> str:
    return iri.rstrip("/#").rsplit("#", 1)[-1].rsplit("/", 1)[-1] or iri


def class_part(g: rdflib.Graph, shapes: rdflib.Graph, shape, cls: URIRef) -> Part:
    instances = set(g.subjects(RDF.type, cls))
    n = len(instances)
    part = Part(label=local_name(str(cls)), targetClass=str(cls), rowCount=n)
    for ps in shapes.objects(shape, SH.property):
        path = shapes.value(ps, SH.path)
        if path is None or path == RDF.type:
            continue
        datatype = shapes.value(ps, SH.datatype) or shapes.value(ps, SH_DATATYPE_TYPO)
        f = Field(name=local_name(str(path)), path=str(path),
                  datatype=str(datatype) if datatype else None,
                  cls=str(shapes.value(ps, SH["class"])) if shapes.value(ps, SH["class"]) else None,
                  nodeKind=str(shapes.value(ps, SH.nodeKind)) if shapes.value(ps, SH.nodeKind) else None)
        mn, mx = shapes.value(ps, SH.minCount), shapes.value(ps, SH.maxCount)
        f.minCount = int(mn) if mn is not None else 0
        f.maxCount = int(mx) if mx is not None else None
        f.type = XSD_TO_TS.get(str(datatype).removeprefix(XSD), "any") if datatype else "any"
        observe(g, instances, path, f)
        part.fields.append(f)
    # sheXer drops properties below its threshold; keep every property the sample uses.
    seen = {f.path for f in part.fields}
    for p in sorted({str(p) for s in instances for p in g.predicates(s)} - seen - {str(RDF.type)}):
        f = Field(name=local_name(p), path=p, minCount=0)
        observe(g, instances, URIRef(p), f)
        part.fields.append(f)
    return part


def observe(g: rdflib.Graph, instances: set, path: URIRef, f: Field) -> None:
    values, using, max_per = [], 0, 0
    for s in instances:
        objs = list(g.objects(s, path))
        if objs:
            using += 1
            max_per = max(max_per, len(objs))
            values += objs
    n = len(instances) or 1
    literals = [v for v in values if isinstance(v, Literal)]
    counter = Counter(str(v) for v in values)
    f.stats = {"count": len(instances), "support": round(using / n, 4),
               "nullPercentage": round(100 * (1 - using / n), 2), "distinct": len(counter), "maxPerInstance": max_per}
    if literals and f.type in ("integer", "number"):
        nums = [float(v) for v in literals if _num(v)]
        if nums:
            f.stats.update({"min": min(nums), "max": max(nums), "mean": sum(nums) / len(nums)})
    elif literals:
        s = sorted(str(v) for v in literals)
        f.stats.update({"min": s[0][:200], "max": s[-1][:200]})
    if 0 < len(counter) <= CATEGORICAL_MAX and len(counter) <= 0.2 * len(values) and f.type != "number":
        f.categorical = True
        f.stats["values"] = sorted(counter)
    f.examples = truncate_examples(str(v) for v in values)
    if not f.nodeKind and values:
        kinds = {("Literal" if isinstance(v, Literal) else "BlankNode" if isinstance(v, rdflib.BNode) else "IRI")
                 for v in values}
        if len(kinds) == 1:
            f.nodeKind = str(SH) + kinds.pop()
    if not f.datatype and literals:
        dts = {str(v.datatype) for v in literals if v.datatype}
        if len(dts) == 1 and len(literals) == len(values):
            f.datatype = dts.pop()
            f.type = XSD_TO_TS.get(f.datatype.removeprefix(XSD), "any")


def _num(v: Literal) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def profile(path: Path, token: str, cfg, tmp: Path, detail: dict) -> list[Part]:
    g = parse(Path(path), token, cfg.int("SAMPLE_ROWS") * 10)
    if not len(g):
        raise EngineError("rdf-empty")
    classes = Counter(g.objects(None, RDF.type))
    if not classes:
        raise EngineError("rdf-untyped")
    shapes = shexer_shapes(g)
    by_class = {shapes.value(s, SH.targetClass): s for s in shapes.subjects(RDF.type, SH.NodeShape)}
    parts = []
    for cls, _ in classes.most_common(MAX_CLASSES):
        shape = by_class.get(cls)
        if shape is None:
            shape = rdflib.BNode()      # no sheXer shape: observe the properties only
        parts.append(class_part(g, shapes, shape, cls))
    for part, s in zip(parts, unique_slugs([p.label for p in parts])):
        part.slug = s if len(parts) > 1 else "main"
    return parts

