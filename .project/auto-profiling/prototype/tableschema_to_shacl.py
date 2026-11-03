"""Map an (enriched) Frictionless Table Schema to SHACL, optionally as a cube:Constraint.

Usage:
  python tableschema_to_shacl.py out.json --base https://example.org/structure/x [--cube]
"""
import argparse
import json
import re

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF, SH, XSD

CUBE = Namespace("https://cube.link/")
META = Namespace("https://cube.link/meta/")
SCHEMA = Namespace("http://schema.org/")
QUDT = Namespace("http://qudt.org/schema/qudt/")
CSVW = Namespace("http://www.w3.org/ns/csvw#")
PROF = Namespace("https://example.org/prof#")   # placeholder for the profile vocabulary

# Table Schema type → (xsd datatype, default qudt scale type)
TYPES = {
    "string": (XSD.string, QUDT.NominalScale),
    "integer": (XSD.integer, QUDT.RatioScale),
    "number": (XSD.decimal, QUDT.RatioScale),
    "boolean": (XSD.boolean, QUDT.NominalScale),
    "date": (XSD.date, QUDT.IntervalScale),
    "datetime": (XSD.dateTime, QUDT.IntervalScale),
    "time": (XSD.time, QUDT.IntervalScale),
    "year": (XSD.gYear, QUDT.IntervalScale),
    "yearmonth": (XSD.gYearMonth, QUDT.IntervalScale),
    "duration": (XSD.duration, QUDT.RatioScale),
    "geojson": (None, None),       # geometry: handled as WKT/GeoSPARQL literal
    "geopoint": (None, None),
    "any": (None, None),
}
GEO_WKT = URIRef("http://www.opengis.net/ont/geosparql#wktLiteral")

# Table Schema constraint → SHACL property
CONSTRAINTS = {
    "minimum": SH.minInclusive, "maximum": SH.maxInclusive,
    "exclusiveMinimum": SH.minExclusive, "exclusiveMaximum": SH.maxExclusive,
    "minLength": SH.minLength, "maxLength": SH.maxLength, "pattern": SH.pattern,
}


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_").lower()


def literal(value, dtype):
    return Literal(value, datatype=dtype) if dtype else Literal(value)


def is_key_dimension(field, primary_key):
    """Heuristic: primary key, temporal or categorical fields are key dimensions; the rest are measures."""
    if field["name"] in primary_key:
        return True
    if field["type"] in ("date", "datetime", "year", "yearmonth"):
        return True
    return field.get("categorical", False) and field["type"] in ("string", "integer", "boolean")


def map_schema(ts: dict, base: str, cube: bool) -> Graph:
    g = Graph()
    for p, ns in [("sh", SH), ("xsd", XSD), ("cube", CUBE), ("meta", META), ("schema", SCHEMA),
                  ("qudt", QUDT), ("csvw", CSVW), ("prof", PROF)]:
        g.bind(p, ns, override=True, replace=True)

    schema = ts.get("schema", ts)
    primary_key = schema.get("primaryKey", [])
    primary_key = [primary_key] if isinstance(primary_key, str) else primary_key
    shape = URIRef(base)
    g.add((shape, RDF.type, SH.NodeShape))
    if cube:
        g.add((shape, RDF.type, CUBE.Constraint))
        g.add((shape, SH.closed, Literal(True)))
        # every observation has rdf:type and cube:observedBy
        for path, node in [(RDF.type, CUBE.Observation), (CUBE.observedBy, None)]:
            ps = BNode()
            g.add((shape, SH.property, ps))
            g.add((ps, SH.path, path))
            g.add((ps, SH.nodeKind, SH.IRI))
            if node:
                lst = BNode(); Collection(g, lst, [node]); g.add((ps, SH["in"], lst))
    if d := ts.get("x-duckdbDialect") or ts.get("dialect"):
        dialect = BNode()
        g.add((shape, CSVW.dialect, dialect))
        if "delimiter" in d:
            g.add((dialect, CSVW.delimiter, Literal(d["delimiter"])))
        if "header" in d:
            g.add((dialect, CSVW.header, Literal(bool(d["header"]))))

    for order, f in enumerate(schema["fields"]):
        ps = URIRef(f"{base}/{slug(f['name'])}")
        g.add((shape, SH.property, ps))
        g.add((ps, RDF.type, SH.PropertyShape))
        g.add((ps, SH.path, URIRef(f.get("rdfType") or f"{base}/col/{slug(f['name'])}")))
        g.add((ps, SH.name, Literal(f.get("title", f["name"]))))
        g.add((ps, SCHEMA.name, Literal(f.get("title", f["name"]))))
        g.add((ps, SH.order, Literal(order)))
        if f.get("description"):
            g.add((ps, SH.description, Literal(f["description"])))

        dtype, scale = TYPES.get(f["type"], (None, None))
        if f["type"] in ("geojson", "geopoint"):
            dtype = GEO_WKT
        codes = f.get("constraints", {}).get("enum") or (
            f.get("stats", {}).get("values") if f.get("categorical") else None)
        if dtype:
            g.add((ps, SH.datatype, dtype))

        c = f.get("constraints", {})
        required = c.get("required") or f["name"] in primary_key \
            or f.get("stats", {}).get("nullPercentage", 100) == 0
        g.add((ps, SH.minCount, Literal(1 if required else 0)))
        g.add((ps, SH.maxCount, Literal(1)))
        for key, prop in CONSTRAINTS.items():
            if key in c:
                g.add((ps, prop, literal(c[key], dtype if prop != SH.pattern else None)))
        if codes:
            lst = BNode(); Collection(g, lst, [literal(v, dtype) for v in codes]); g.add((ps, SH["in"], lst))

        if cube:
            key = is_key_dimension(f, primary_key)
            g.add((ps, RDF.type, CUBE.KeyDimension if key else CUBE.MeasureDimension))
            if scale:
                g.add((ps, QUDT.scaleType, QUDT.NominalScale if key and scale == QUDT.RatioScale else scale))
            if f["type"] in ("date", "datetime", "year", "yearmonth"):
                g.add((ps, META.dataKind, _time_kind(g, f["type"])))
            if f.get("unit"):
                g.add((ps, QUDT.unit, URIRef(f["unit"])))

        # observed profile kept beside, not inside, the constraint
        if s := f.get("stats"):
            pr = BNode()
            g.add((ps, PROF.observed, pr))
            for k in ("count", "approxUnique", "nullPercentage", "min", "max", "mean", "q50"):
                if k in s:
                    g.add((pr, PROF[k], Literal(s[k])))
    return g


def _time_kind(g, ts_type):
    kind = BNode()
    g.add((kind, RDF.type, URIRef("http://www.w3.org/2006/time#GeneralDateTimeDescription")))
    unit = {"date": "unitDay", "datetime": "unitSecond", "year": "unitYear", "yearmonth": "unitMonth"}[ts_type]
    g.add((kind, URIRef("http://www.w3.org/2006/time#unitType"), URIRef(f"http://www.w3.org/2006/time#{unit}")))
    return kind


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tableschema")
    ap.add_argument("--base", required=True)
    ap.add_argument("--cube", action="store_true")
    a = ap.parse_args()
    print(map_schema(json.load(open(a.tableschema)), a.base, a.cube).serialize(format="turtle"))
