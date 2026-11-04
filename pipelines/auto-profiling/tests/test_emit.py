import os
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.compare import isomorphic, to_isomorphic
from rdflib.namespace import RDF, SH

from autoprof.emit import Emitter, vocab_graph
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


def test_output_conforms_to_shapes():
    from pyshacl import validate
    s = Structure.read(FIXTURES / "bevoelkerung.profile.json")
    stub = Structure(id="stub", dataset="https://opendata.swiss/set/data/x",
                     representative="https://opendata.swiss/set/distribution/y",
                     distributions=["https://opendata.swiss/set/distribution/y"],
                     status="skipped", statusReason="out-of-scope:WMS", declared=["WMS"])
    em = Emitter(BASE, URIRef(BASE + "run/test"))
    g = em.structure(s, {}) + em.structure(stub, {}) + vocab_graph(PIPELINE / "vocab" / "prof.ttl", BASE)
    conforms, _, text = validate(g, shacl_graph=Graph().parse(PIPELINE / "shapes.ttl"))
    assert conforms, text


def test_shapes_reject_a_profiled_structure_without_parts():
    from pyshacl import validate
    broken = Structure(id="broken", dataset="https://opendata.swiss/set/data/x",
                       representative="https://opendata.swiss/set/distribution/z",
                       distributions=["https://opendata.swiss/set/distribution/z"])
    g = Emitter(BASE, URIRef(BASE + "run/test")).structure(broken, {})
    conforms, _, _ = validate(g, shacl_graph=Graph().parse(PIPELINE / "shapes.ttl"))
    assert not conforms


def test_base_iri_moves_vocab():
    g = vocab_graph(PIPELINE / "vocab" / "prof.ttl", "https://visoto.example/ap/")
    assert (URIRef("https://visoto.example/ap/prof#Structure"), None, None) in g
    assert not any("example.org/auto-profiling/prof#" in str(s) for s in g.subjects())


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
