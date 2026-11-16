"""Concept-matching phase 3b inputs: dataset context, functional dependencies, candidate keys, patterns."""
import json

from rdflib import URIRef
from rdflib.namespace import RDF

from autoprof.emit import AP, Emitter, vocab_graph
from autoprof.engines import tabular
from autoprof.model import Field, Part, Structure, value_pattern
from autoprof.resolve import dataset_context
from autoprof.sniff import encoding, sniff
from conftest import FIXTURES
from test_emit import BASE, PIPELINE, shapes

DCT = "http://purl.org/dc/terms/"
DCAT = "http://www.w3.org/ns/dcat#"


def csv_part(cfg, tmp_path, path):
    head = path.read_bytes()
    _, detail = sniff(head)
    detail["encoding"] = encoding(head)
    [part] = tabular.profile(path, "CSV", cfg, tmp_path / "work", detail)
    return part


def persons_csv(tmp_path):
    """A denormalised table: persons with their municipality of residence and its name."""
    towns = [(351, "Bern"), (261, "Zürich"), (6621, "Genève"), (1061, "Luzern")]
    rows = ["person_id;alter;wohngemeinde_bfs;gemeinde_name"]
    for i in range(60):
        bfs, name = towns[i % 4]
        rows.append(f"P{i:04d};{20 + i % 37};{bfs};{name}")
    path = tmp_path / "persons.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_denormalised_table_dependencies(cfg, tmp_path):
    part = csv_part(cfg, tmp_path, persons_csv(tmp_path))
    assert part.candidateKeys == ["person_id"]
    deps = {d["determinant"]: d for d in part.dependencies}
    assert deps["wohngemeinde_bfs"]["dependents"] == ["gemeinde_name"]
    assert deps["wohngemeinde_bfs"]["rows"] == 60 and deps["wohngemeinde_bfs"]["distinct"] == 4
    assert deps["gemeinde_name"]["dependents"] == ["wohngemeinde_bfs"]     # 1:1, both ways
    # alter repeats too, but determines nothing; the row key is not reported as a determinant
    assert "alter" not in deps and "person_id" not in deps


def test_bevoelkerung_municipality_determines_its_attributes(cfg, tmp_path):
    part = csv_part(cfg, tmp_path, FIXTURES / "bevoelkerung.csv")
    deps = {d["determinant"]: set(d["dependents"]) for d in part.dependencies}
    assert {"Gemeinde", "Kanton"} <= deps["BFS_Nr"]
    assert "Einwohner" not in deps["BFS_Nr"]      # changes over the reference dates


def test_no_dependencies_from_a_small_sample(cfg, tmp_path):
    path = tmp_path / "small.csv"
    path.write_text("a;b\n" + "".join(f"{i % 3};x{i % 3}\n" for i in range(10)), encoding="utf-8")
    part = csv_part(cfg, tmp_path, path)
    assert part.dependencies == [] and part.candidateKeys == []


def test_value_pattern():
    assert value_pattern([f"CHE-{i}{i}{i}.456.78{i}" for i in range(1, 7)]) == r"^CHE\-\d{3}\.456\.\d{3}$"
    assert value_pattern(["A-0012", "A-0457", "A-1000", "A-0001", "A-9999"]) == r"^A\-\d{4}$"
    assert value_pattern(["BE", "ZH", "LU", "UR", "SZ", "GE"]) == "^[A-Z]{2}$"
    assert value_pattern(["Zürich", "Bern", "Genève", "Basel", "Luzern"]) == r"^\p{L}{4,6}$"
    assert value_pattern(["1", "22", "333", "4444", "55555"]) == r"^\d{1,5}$"
    # free text has no dominant shape; too few values say nothing
    assert value_pattern(["Bahnhofstrasse 12", "Rue de Lausanne 5", "Seestrasse 3", "Hauptgasse 1a",
                          "Via Cantonale"]) is None
    assert value_pattern(["AB", "CD", "EF"]) is None
    # one stray value of twenty does not break the shape
    assert value_pattern([f"{i:04d}" for i in range(19)] + ["n/a"]) == r"^\d{4}$"


def test_dataset_context_keeps_every_language():
    ds = "https://opendata.swiss/set/data/x"
    rows = [
        {"dataset": ds, "p": DCT + "title", "o": "Gemeinden", "o@lang": "de"},
        {"dataset": ds, "p": DCT + "title", "o": "Communes", "o@lang": "fr"},
        {"dataset": ds, "p": DCT + "description", "o": "x" * 600, "o@lang": "it"},
        {"dataset": ds, "p": DCAT + "keyword", "o": "Gemeinde", "o@lang": "de"},
        {"dataset": ds, "p": DCAT + "keyword", "o": "opendata.swiss", "o@lang": "de"},
        {"dataset": ds, "p": DCAT + "theme", "o": "http://publications.europa.eu/resource/authority/data-theme/REGI"},
    ]
    c = dataset_context(rows)[ds]
    assert c["title"] == {"de": "Gemeinden", "fr": "Communes"}
    assert len(c["description"]["it"]) == 500
    assert c["keywords"] == {"de": ["Gemeinde"]}
    assert c["themes"] == ["http://publications.europa.eu/resource/authority/data-theme/REGI"]


def structure_with_context() -> Structure:
    part = Part(rowCount=60, candidateKeys=["person_id"],
                dependencies=[{"determinant": "wohngemeinde_bfs", "dependents": ["gemeinde_name"],
                               "rows": 60, "distinct": 4}],
                fields=[Field(name="person_id", type="string", stats={"count": 60, "distinct": 60},
                              sample=["P0001"], pattern=r"^P\d{4}$"),
                        Field(name="wohngemeinde_bfs", type="integer", stats={"count": 60}),
                        Field(name="gemeinde_name", type="string", stats={"count": 60})])
    return Structure(id="persons", dataset="https://opendata.swiss/set/data/x",
                     representative="https://opendata.swiss/set/distribution/y",
                     distributions=["https://opendata.swiss/set/distribution/y"], engine="tabular", parts=[part])


def test_emit_dependencies_patterns_and_container_record():
    from pyshacl import validate
    em = Emitter(BASE, URIRef(BASE + "run/test"))
    em.dataset_context = {"https://opendata.swiss/set/data/x": {"title": {"de": "Personen"}}}
    s = structure_with_context()
    g = em.structure(s, {s.representative: {"title": "Personen 2025"}})
    N = URIRef(BASE + "structure/persons/main")
    slot = lambda name: URIRef(f"{N}/{name}")
    assert set(g.objects(N, AP.candidateKey)) == {slot("person_id")}
    [fd] = g.objects(N, AP.functionalDependency)
    assert g.value(fd, AP.determinant) == slot("wohngemeinde_bfs")
    assert set(g.objects(fd, AP.dependent)) == {slot("gemeinde_name")}
    assert g.value(fd, AP.determinantValues).value == 4
    assert str(g.value(g.value(slot("person_id"), AP.observed), AP.pattern)) == r"^P\d{4}$"
    assert next(r for r in em.slots if r["name"] == "person_id")["pattern"] == r"^P\d{4}$"

    [c] = em.containers
    assert c["iri"] == str(N) and c["path"] == "main"
    assert c["dataset"] == {"iri": s.dataset, "title": {"de": "Personen"}}
    assert c["distribution"]["title"] == "Personen 2025"
    assert [col["name"] for col in c["columns"]] == ["person_id", "wohngemeinde_bfs", "gemeinde_name"]
    assert c["columns"][0]["slot"] == str(slot("person_id"))
    assert c["candidateKeys"] == ["person_id"] and c["dependencies"] == s.parts[0].dependencies
    json.dumps(c)       # serialisable as a containers.jsonl line

    conforms, _, text = validate(g + vocab_graph(PIPELINE / "vocab" / "ap.ttl"), shacl_graph=shapes())
    assert conforms, text
    assert len(list(g.subjects(RDF.type, AP.FunctionalDependency))) == 1
