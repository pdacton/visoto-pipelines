import os
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.compare import isomorphic, to_isomorphic
from rdflib.namespace import DCAT, DCTERMS, RDF, SH, XSD

from autoprof.emit import AP, CSVW, RML, Emitter, vocab_graph
from autoprof.model import Structure
from conftest import FIXTURES

BASE = "https://example.org/auto-profiling/"
CUBE = Namespace("https://cube.link/")
PIPELINE = Path(__file__).resolve().parent.parent


def emit_bevoelkerung() -> Graph:
    s = Structure.read(FIXTURES / "bevoelkerung.profile.json")
    em = Emitter(BASE, URIRef(BASE + "run/test"))
    return em.structure(s, {})


def test_golden_turtle():
    """Fixture profile JSON → expected Turtle. UPDATE_GOLDEN=1 rewrites the expected file."""
    g = emit_bevoelkerung()
    expected = FIXTURES / "bevoelkerung.expected.ttl"
    if os.environ.get("UPDATE_GOLDEN"):
        g.serialize(expected, format="turtle")
    want = Graph().parse(expected)
    assert isomorphic(to_isomorphic(canonical(g)), to_isomorphic(canonical(want)))


def canonical(g: Graph) -> Graph:
    """Literals rebuilt from their values: Turtle writes 2564.33 as 2.56433E3."""
    out = Graph()
    for s, p, o in g:
        if isinstance(o, Literal) and o.datatype and o.value is not None:
            o = Literal(o.value, datatype=o.datatype)
        out.add((s, p, o))
    return out


def dims(g: Graph) -> dict:
    """property name → (dimension class, datatype, sh:in values) for every cube dimension."""
    out = {}
    for ps in g.subjects(RDF.type, SH.PropertyShape):
        kind = CUBE.KeyDimension if (ps, RDF.type, CUBE.KeyDimension) in g else \
            CUBE.MeasureDimension if (ps, RDF.type, CUBE.MeasureDimension) in g else None
        lst = g.value(ps, SH["in"])
        values = frozenset(str(v) for v in Collection(g, lst)) if lst else None
        out[str(g.value(ps, SH.name))] = (kind, g.value(ps, SH.datatype), values)
    return out


def test_equivalent_to_prototype_cube():
    """The bevoelkerung example gives the cube.ttl of the 2026-11-03 prototype: same dimensions,
    datatypes and code lists (IRIs and the profile vocabulary differ by design)."""
    ours = emit_bevoelkerung()
    proto = Graph().parse(FIXTURES / "bevoelkerung.cube.ttl")
    assert len(list(ours.subjects(RDF.type, CUBE.Constraint))) == 1
    assert dims(ours) == dims(proto)


def shapes() -> Graph:
    """The shapes graph scripts/validate.sh builds: every file in pipeline.env SHAPES."""
    from autoprof.config import Config
    g = Graph()
    for f in Config.load(PIPELINE)["SHAPES"].split():
        g.parse(PIPELINE / f)
    return g


def test_output_conforms_to_shapes():
    from pyshacl import validate
    s = Structure.read(FIXTURES / "bevoelkerung.profile.json")
    stub = Structure(id="stub", dataset="https://opendata.swiss/set/data/x",
                     representative="https://opendata.swiss/set/distribution/y",
                     distributions=["https://opendata.swiss/set/distribution/y"],
                     status="skipped", statusReason="out-of-scope:WMS", declared=["WMS"])
    em = Emitter(BASE, URIRef(BASE + "run/test"))
    g = em.structure(s, {}) + em.structure(stub, {}) + vocab_graph(PIPELINE / "vocab" / "ap.ttl")
    conforms, _, text = validate(g, shacl_graph=shapes())
    assert conforms, text


def test_shapes_reject_a_profiled_structure_without_parts():
    from pyshacl import validate
    broken = Structure(id="broken", dataset="https://opendata.swiss/set/data/x",
                       representative="https://opendata.swiss/set/distribution/z",
                       distributions=["https://opendata.swiss/set/distribution/z"])
    g = Emitter(BASE, URIRef(BASE + "run/test")).structure(broken, {})
    conforms, _, _ = validate(g, shacl_graph=shapes())
    assert not conforms


def test_every_ap_term_is_defined_in_the_vocabulary():
    vocab = vocab_graph(PIPELINE / "vocab" / "ap.ttl")
    g = emit_bevoelkerung()
    used = {t for triple in g for t in triple if isinstance(t, URIRef) and str(t).startswith(str(AP))}
    used -= {URIRef(BASE)}
    assert used and all((t, None, None) in vocab for t in used), sorted(t for t in used if (t, None, None) not in vocab)


def test_no_prof_terms_left():
    g = emit_bevoelkerung()
    assert not any("prof#" in str(t) for triple in g for t in triple)


def test_logical_source_of_a_csv():
    g = emit_bevoelkerung()
    [ls] = g.subjects(RDF.type, RML.LogicalSource)
    container = g.value(ls, AP.container)
    assert (None, DCTERMS.hasPart, container) in g
    assert g.value(ls, RML.referenceFormulation) == RML.CSV
    dialect = g.value(ls, CSVW.dialect)
    assert dialect is not None and g.value(dialect, CSVW.delimiter) is not None
    assert g.value(container, CSVW.dialect) is None   # moved off the shape


def test_logical_source_of_records_and_sheets():
    from autoprof.model import Field, Part
    s = Structure(id="j", dataset="https://example.org/d", representative="https://example.org/x",
                  distributions=["https://example.org/x"], engine="tabular",
                  parts=[Part(slug="data", dialect={"recordsPath": "/results"}, fields=[Field(name="a", type="string")]),
                         Part(slug="sheet_2", label="Sheet 2", tableName="Sheet 2", dialect={"header": True, "skipRows": 3},
                              fields=[Field(name="b", type="integer")])])
    g = Emitter(BASE, URIRef(BASE + "run/test")).structure(s, {"https://example.org/x": {
        "downloadURL": "https://example.org/file.json"}})
    sources = {str(g.value(ls, AP.container)).rsplit("/", 1)[-1]: ls for ls in g.subjects(RDF.type, RML.LogicalSource)}
    assert str(g.value(sources["data"], RML.iterator)) == "$.results[*]"
    assert g.value(sources["data"], RML.referenceFormulation) == RML.JSONPath
    assert str(g.value(sources["sheet_2"], AP.tableName)) == "Sheet 2"
    assert g.value(URIRef("https://example.org/x"), DCAT.downloadURL) == Literal("https://example.org/file.json", datatype=XSD.anyURI)


def test_json_path():
    from autoprof.emit import json_path
    assert json_path("/") == "$[*]"
    assert json_path("/results") == "$.results[*]"
    assert json_path("/my key") == "$['my key'][*]"


def test_slots_jsonl_records():
    s = Structure.read(FIXTURES / "bevoelkerung.profile.json")
    em = Emitter(BASE, URIRef(BASE + "run/test"))
    g = em.structure(s, {})
    by_name = {r["name"]: r for r in em.slots}
    assert len(em.slots) == len(list(g.subjects(RDF.type, AP.Slot)))
    r = next(iter(by_name.values()))
    assert set(r["key"]) == {"dataset", "distributions", "container", "sourceName"}
    assert r["key"]["container"] == "main" and r["key"]["dataset"] == s.dataset
    for r in em.slots:   # the fingerprint triple matches the record
        assert str(g.value(URIRef(r["iri"]), AP.fingerprint)) == r["fingerprint"]
        assert r["name"] not in r["neighbours"] or len(set(f.name for p in s.parts for f in p.fields)) < len(r["neighbours"])


def test_fingerprint_ignores_sample_order_and_name_spelling():
    from autoprof.emit import fingerprint
    a = fingerprint("BFS-Nr", "http://www.w3.org/2001/XMLSchema#integer", ["261", "351"])
    assert a == fingerprint("bfs_nr", "http://www.w3.org/2001/XMLSchema#integer", ["351", "261"])
    assert a != fingerprint("bfs_nr", "http://www.w3.org/2001/XMLSchema#string", ["351", "261"])
    assert a != fingerprint("bfs_nr", "http://www.w3.org/2001/XMLSchema#integer", ["351"])


def test_value_sample_is_deterministic_and_bounded():
    from autoprof.model import value_sample
    values = [str(i) for i in range(1000)] + [None, "", "  ", "x" * 500]
    a = value_sample(values, 200)
    assert a == value_sample(reversed(values), 200)
    assert len(a) == 200 and len(set(a)) == 200
    assert all(len(v) <= 200 for v in value_sample(["x" * 500], 5))
    assert value_sample([None, "", 1, 1, "1"], 5) == ["1"]


def test_status_stub_links_every_member():
    stub = Structure(id="s", dataset="https://opendata.swiss/set/data/x", representative="d:1",
                     distributions=["d:1", "d:2"], status="failed", statusReason="html-page")
    g = Emitter(BASE, URIRef(BASE + "run/test")).structure(stub, {})
    target = URIRef(BASE + "structure/s")
    assert {str(d) for d in g.subjects(URIRef("http://purl.org/dc/terms/conformsTo"), target)} == {"d:1", "d:2"}


def test_relative_iris_from_data_are_dropped():
    from autoprof.emit import absolute
    assert absolute("https://x.org/a") == URIRef("https://x.org/a")
    assert absolute("urn:x:1") == URIRef("urn:x:1")
    assert absolute("-") is None and absolute("") is None and absolute("a b:c") is None


def test_integer_beyond_64_bits_is_a_decimal():
    from rdflib.namespace import XSD
    from autoprof.emit import Emitter
    em = Emitter("https://example.org/", None)
    assert em.literal(2**63 - 1, XSD.integer).datatype == XSD.integer
    big = em.literal(115498772442761859845586944, XSD.integer)
    assert big.datatype == XSD.decimal and int(big.toPython()) == 115498772442761859845586944
