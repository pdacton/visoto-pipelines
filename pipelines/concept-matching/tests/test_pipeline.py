"""End to end on a miniature pipeline folder: all stages, the graph validated, the plan's done criteria."""
import json

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import DCAT, DCTERMS, RDF, SH

from cmatch import concepts, confirm, emit, linkvalues, report, seed
from cmatch.registry import Registry
from conftest import MUNI, slot, write_slots

AP = Namespace("https://register.ld.admin.ch/mds/ontology/ap/")
MUNI_VALUES = ["261", "351", "2196", "5586", "6621", "371"]


def slots_v1():
    return [
        slot("BFS_Nr", MUNI_VALUES, dataset="https://example.org/population", fingerprint="fp-muni",
             structure="https://example.org/s1"),
        slot("Einwohner", ["1200", "3400", "980", "15000", "220"], dataset="https://example.org/population",
             fingerprint="fp-pop", structure="https://example.org/s1"),
        # another dataset, same column (same fingerprint)
        slot("BFS_Nr", MUNI_VALUES, dataset="https://example.org/boundaries", fingerprint="fp-muni",
             structure="https://example.org/s2", container="gemeinden"),
        slot("Kanton", ["ZH", "BE", "LU", "GE", "TI", "VS"], dataset="https://example.org/boundaries",
             type_="string", fingerprint="fp-kt", structure="https://example.org/s2", container="gemeinden"),
        slot("GWR_EGID", ["190", "1234567", "88", "9021", "33"], dataset="https://example.org/buildings",
             fingerprint="fp-egid", structure="https://example.org/s3"),
        slot("Datum", ["2024-01-01", "2023-12-31"], dataset="https://example.org/buildings", type_="date",
             datatype="http://www.w3.org/2001/XMLSchema#date", format="%d.%m.%Y", fingerprint="fp-date",
             structure="https://example.org/s3"),
    ]


def run_all(cfg):
    for stage in (seed, confirm, linkvalues, concepts, emit, report):
        stage.run(cfg)


def output_graph(cfg) -> Graph:
    g = Graph()
    for part in sorted((cfg.out / "parts").glob("*.nt")):
        g.parse(part, format="nt")
    return g


def shapes(cfg) -> Graph:
    g = Graph()
    for f in cfg["SHAPES"].split():
        g.parse(cfg.pipeline_dir / f)
    return g


def profiling_graph(slots) -> Graph:
    """The auto-profiling triples the comparison query walks (dataset → distribution → structure → slot)."""
    g = Graph()
    for s in slots:
        ds, dist = URIRef(s["key"]["dataset"]), URIRef(s["key"]["distributions"][0])
        g.add((ds, DCAT.distribution, dist))
        g.add((dist, DCTERMS.conformsTo, URIRef(s["structure"])))
        g.add((URIRef(s["structure"]), DCTERMS.hasPart, URIRef(s["container"]["iri"])))
        g.add((URIRef(s["container"]["iri"]), SH.property, URIRef(s["iri"])))
    return g


COMPARISON = """
PREFIX ap: <https://register.ld.admin.ch/mds/ontology/ap/>
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX sh: <http://www.w3.org/ns/shacl#>
SELECT ?other (COUNT(DISTINCT ?s1) AS ?sharedSlots) WHERE {
  <%s> dcat:distribution/dcterms:conformsTo/dcterms:hasPart/sh:property ?s1 .
  ?s1 ap:%s/dcterms:isVersionOf? ?vd .
  ?s2 ap:%s/dcterms:isVersionOf? ?vd .
  ?other dcat:distribution/dcterms:conformsTo/dcterms:hasPart/sh:property ?s2 .
  FILTER(?other != <%s>)
} GROUP BY ?other ORDER BY DESC(?sharedSlots)"""


def comparable(g: Graph, dataset: str, shortcut: str = "valueDomain") -> dict:
    return {str(r[0]): int(r[1]) for r in g.query(COMPARISON % (dataset, shortcut, shortcut, dataset))}


def links_by_slot(cfg) -> dict:
    return {r["slot"]: r for r in linkvalues.read(cfg)}


# --- phase 1 and 2 -------------------------------------------------------------------------

def test_values_are_linked_and_the_graph_validates(pipeline):
    from pyshacl import validate
    slots = slots_v1()
    write_slots(pipeline, slots)
    run_all(pipeline)
    links = links_by_slot(pipeline)
    reg = Registry.load(pipeline.registry_dir, pipeline.base_iri)
    muni = links[slots[0]["iri"]]
    vd = reg.get("valuedomains", muni["valueDomain"])
    assert vd["kind"] == "codelist" and vd["permissibleValues"] == MUNI       # valid in both versions → the list
    assert muni["matches"][0]["evidence"]["method"] == "code-overlap"
    assert reg.get("valuedomains", links[slots[3]["iri"]]["valueDomain"])["id"] == "GDE"     # cantons, level 1
    assert links[slots[4]["iri"]]["valueDomain"].endswith("/identifier/egid")
    assert reg.get("valuedomains", links[slots[5]["iri"]]["valueDomain"])["id"] == "described/date-dd.mm.yyyy"
    assert reg.get("valuedomains", links[slots[1]["iri"]]["valueDomain"])["id"] == "described/integer"
    g = output_graph(pipeline)
    conforms, _, text = validate(g, shacl_graph=shapes(pipeline))
    assert conforms, text
    # done criterion of phase 2: the comparison query finds the technically comparable dataset
    full = g + profiling_graph(slots)
    assert comparable(full, "https://example.org/population")["https://example.org/boundaries"] >= 1


def test_a_persons_match_survives_a_slot_iri_change(pipeline):
    slots = slots_v1()
    write_slots(pipeline, slots)
    seed.run(pipeline)
    reg = Registry.load(pipeline.registry_dir, pipeline.base_iri)
    v2024 = next(e["iri"] for e in reg.all("valuedomains") if e["id"] == "GDE/2024")
    (pipeline.pipeline_dir / "confirmations.csv").write_text(
        ",".join(confirm.COLUMNS) + "\n"
        f"https://example.org/population,https://example.org/population/dist,main,BFS_Nr,{v2024},exactMatch,"
        "steward@example.org,2026-11-10,checked by hand\n"
        "https://example.org/nowhere,,main,X,https://example.org/mds/valuedomain/GDE,,someone,,\n")
    run_all(pipeline)
    links = links_by_slot(pipeline)
    first = links[slots[0]["iri"]]
    assert first["valueDomain"] == v2024 and any(m.get("person") for m in first["matches"])
    assert not any(m["kind"] == "valueDomain" and not m.get("person") for m in first["matches"])
    # offered to the other slot with the same fingerprint
    assert any(c["evidence"]["method"] == "confirmed-elsewhere" and c["entry"] == v2024
               for c in links[slots[2]["iri"]]["candidates"])
    status = {c["line"]: c["status"] for c in confirm.load(pipeline)}
    assert status == {2: "placed", 3: "unplaced"}

    # auto-profiling reruns with another representative distribution: new slot IRIs, same key
    moved = slots_v1()
    for s in moved:
        if s["structure"] == "https://example.org/s1":
            s["iri"] = s["iri"].replace("/s1/", "/s1-new/")
            s["structure"] = "https://example.org/s1-new"
            s["key"]["distributions"] = s["key"]["distributions"] + ["https://example.org/population/csv"]
    write_slots(pipeline, moved)
    run_all(pipeline)
    links = links_by_slot(pipeline)
    assert links[moved[0]["iri"]]["valueDomain"] == v2024
    c = next(c for c in confirm.load(pipeline) if c["status"] == "placed")
    assert c["slot"] == moved[0]["iri"]
    tg = Graph().parse(pipeline.out / "concept-matching-confirmations.ttl")
    assert (URIRef(moved[0]["iri"]), AP.match, None) in tg

    # validates against the ap: shapes
    from pyshacl import validate
    conforms, _, text = validate(tg, shacl_graph=Graph().parse(pipeline.pipeline_dir / "vocab" / "ap-shapes.ttl"))
    assert conforms, text


def test_drift_is_flagged(pipeline):
    slots = slots_v1()
    write_slots(pipeline, slots)
    seed.run(pipeline)
    sex = "https://example.org/mds/valuedomain/SEX"
    (pipeline.pipeline_dir / "confirmations.csv").write_text(
        ",".join(confirm.COLUMNS) + f"\nhttps://example.org/population,,main,Einwohner,{sex},,a@b.ch,,\n")
    run_all(pipeline)
    rec = links_by_slot(pipeline)[slots[1]["iri"]]
    assert rec["valueDomain"] == sex and rec["notes"][0]["drift"] == sex
    assert "### Drift" in (pipeline.out / "report.md").read_text()


# --- phase 3 ---------------------------------------------------------------------------------

def answers(pipeline, rows):
    d = pipeline.pipeline_dir / "answers"
    d.mkdir(exist_ok=True)
    (d / "test.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    pipeline.values["CONCEPT_MODEL"] = "answers"


def test_concepts_from_answers_and_rerun_creates_nothing(pipeline):
    from pyshacl import validate
    slots = slots_v1()
    write_slots(pipeline, slots)
    answers(pipeline, [
        {"fingerprint": "fp-muni", "confidence": 0.95, "rationale": "Official municipality numbers.",
         "objectClass": {"new": {"title": {"en": "Municipality"}, "closeMatch": ["http://schema.org/AdministrativeArea"]}},
         "property": {"new": {"title": {"en": "BFS municipality number"}, "closeMatch": ["http://schema.org/identifier"]}}},
        {"fingerprint": "fp-kt", "confidence": 0.9,
         "objectClass": {"new": {"title": {"en": "Municipality"}}},
         "property": {"new": {"title": {"en": "canton"}}},
         "codeList": "https://example.org/mds/valuedomain/SEX"},             # contradicted by the values
        {"fingerprint": "fp-pop", "confidence": 0.5,                          # below the threshold: candidate only
         "objectClass": {"new": {"title": {"en": "Municipality"}}},
         "property": {"new": {"title": {"en": "population"}}}},
        {"fingerprint": "fp-date", "none": True},
    ])
    run_all(pipeline)
    links = links_by_slot(pipeline)
    reg = Registry.load(pipeline.registry_dir, pipeline.base_iri)
    a, b = links[slots[0]["iri"]], links[slots[2]["iri"]]
    assert a["dataElementConcept"] and a["dataElementConcept"] == b["dataElementConcept"]
    assert len(reg.all("objectclasses")) == 1          # "Municipality" named by three answers, created once
    assert a["dataElement"] == b["dataElement"]
    de = reg.get("dataelements", a["dataElement"])
    assert de["valueDomain"] == a["valueDomain"] and de["path"] == "http://schema.org/identifier"
    dec = reg.get("dataelementconcepts", a["dataElementConcept"])
    assert reg.get("objectclasses", dec["objectClass"])["status"] == "UnderDevelopment"
    assert any("dropped" in n for n in links[slots[3]["iri"]]["notes"])
    assert links[slots[3]["iri"]]["valueDomain"].endswith("/valuedomain/GDE")    # the code list kept
    pop = links[slots[1]["iri"]]
    assert not pop.get("dataElementConcept") and any(c["kind"] == "dataElementConcept" for c in pop["candidates"])
    assert {"concept": "none"} in links[slots[5]["iri"]]["notes"]
    # the containers' main object class follows from their concepts
    mc = json.loads((pipeline.out / "main-object-classes.json").read_text())
    assert mc[slots[2]["container"]["iri"]] == dec["objectClass"]
    g = output_graph(pipeline)
    conforms, _, text = validate(g, shacl_graph=shapes(pipeline))
    assert conforms, text
    full = g + profiling_graph(slots)
    assert "https://example.org/boundaries" in comparable(full, "https://example.org/population", "dataElementConcept")
    # done criterion of phase 3: a second run creates no new entries for unchanged slots
    before = {k: set(v) for k, v in reg.entries.items()}
    (pipeline.pipeline_dir / "answers" / "test.jsonl").unlink()      # the cache answers now
    run_all(pipeline)
    after = Registry.load(pipeline.registry_dir, pipeline.base_iri)
    assert {k: set(v) for k, v in after.entries.items()} == before
    assert links_by_slot(pipeline)[slots[0]["iri"]]["dataElementConcept"] == a["dataElementConcept"]


def test_unanswered_fingerprints_become_requests(pipeline):
    write_slots(pipeline, slots_v1())
    run_all(pipeline)
    reqs = [json.loads(l) for l in (pipeline.out / "concept-requests.jsonl").read_text().splitlines()]
    assert {r["fingerprint"] for r in reqs} == {s["fingerprint"] for s in slots_v1()}
    muni = next(r for r in reqs if r["fingerprint"] == "fp-muni")
    assert muni["slot"]["name"] == "BFS_Nr" and muni["slot"]["valueDomain"]


def test_embedding_index_finds_near_labels():
    idx = concepts.Index(concepts.HashingEmbedder())
    for i, t in enumerate(["Municipality", "Person", "Building", "Enterprise"]):
        idx.add({"iri": f"x:{i}", "title": {"en": t}})
    assert idx.nearest("municipalities of the canton", 1)[0][0]["title"]["en"] == "Municipality"
    assert idx.nearest("Gebäude building", 1)[0][0]["title"]["en"] == "Building"


# --- report and gold sets ------------------------------------------------------------------

def test_gold_values_precision_and_recall(pipeline):
    slots = slots_v1()
    write_slots(pipeline, slots)
    gold = pipeline.pipeline_dir / "tests"
    gold.mkdir()
    (gold / "gold-values.csv").write_text(
        "dataset,container,source_name,expected,note\n"
        "https://example.org/population,main,BFS_Nr,GDE,\n"
        "https://example.org/boundaries,gemeinden,Kanton,GDE,\n"
        "https://example.org/buildings,main,GWR_EGID,identifier/egid,\n"
        "https://example.org/population,main,Einwohner,described,\n"
        "https://example.org/buildings,main,Datum,SEX,wrong on purpose\n")
    run_all(pipeline)
    _, stats = report.build(pipeline)
    gv = stats["gold_values"]
    assert (gv["tp"], gv["fp"], gv["fn"]) == (3, 0, 1)
    assert gv["precision"] == 1.0 and gv["recall"] == 0.75
    text = (pipeline.out / "report.md").read_text()
    assert "## Review queue" in text and "## Registry" in text


def test_tune_writes_a_table(pipeline, monkeypatch):
    from cmatch import tune
    write_slots(pipeline, slots_v1())
    run_all(pipeline)
    (pipeline.pipeline_dir / "tests").mkdir(exist_ok=True)
    (pipeline.pipeline_dir / "tests" / "gold-values.csv").write_text(
        "dataset,container,source_name,expected,note\nhttps://example.org/population,main,BFS_Nr,GDE,\n")
    monkeypatch.setattr(tune, "GRID", {"CODE_MIN_CONTAINMENT": ["0.95"], "CODE_MIN_DISTINCT": ["5", "7"],
                                       "CODE_MIN_LEAD": ["0.1"]})
    tune.run(pipeline)
    text = (pipeline.out / "tuning.md").read_text()
    assert "| 0.95 | 5 | 0.1 | 1.00 | 1.00 |" in text and "| 0.95 | 7 | 0.1 | – | 0.00 |" in text


# --- the hosted model, with a fake client (no network) ---------------------------------------

class FakeBlock:
    def __init__(self, text):
        self.type, self.text = "text", text


class FakeResponse:
    def __init__(self, data, stop="end_turn"):
        self.stop_reason, self.content = stop, [FakeBlock(json.dumps(data))]


class FakeClient:
    def __init__(self, replies):
        self.replies, self.requests = replies, []
        self.beta = self
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        fp = json.loads(kw["messages"][0]["content"])["fingerprint"]
        return self.replies.get(fp, FakeResponse({}, stop="refusal"))


def part(title=None, iri=None):
    return {"iri": iri, "title": title, "description": f"The {title}." if title else None, "closeMatch": []}


def test_claude_model_with_a_fake_client(pipeline):
    slots = slots_v1()
    write_slots(pipeline, slots)
    seed.run(pipeline)
    confirm.run(pipeline)
    linkvalues.run(pipeline)
    client = FakeClient({
        "fp-muni": FakeResponse({"none": False, "objectClass": part("Municipality"),
                                 "property": part("BFS municipality number"), "codeList": None,
                                 "confidence": 0.93, "rationale": "Official numbers."}),
        "fp-date": FakeResponse({"none": True, "objectClass": part(), "property": part(), "codeList": None,
                                 "confidence": 0.9, "rationale": "Layout column."}),
    })
    model = concepts.ClaudeModel(client=client)
    reg = Registry.load(pipeline.registry_dir, pipeline.base_iri)
    linker = concepts.Linker(pipeline, reg, model)
    links = {r["slot"]: r for r in linker.link(slots, linkvalues.read(pipeline))}
    assert links[slots[0]["iri"]]["dataElementConcept"] == links[slots[2]["iri"]]["dataElementConcept"]
    assert {"concept": "none"} in links[slots[5]["iri"]]["notes"]
    # one call per fingerprint; refusals stay requests
    assert model.calls == 5 and len(linker.requests) == 3
    req = client.requests[0]
    assert req["output_config"]["format"]["schema"] == concepts.ANSWER_SCHEMA and req["fallbacks"] == "default"


def test_claude_model_needs_explicit_permission(pipeline):
    import pytest
    pipeline.values["CONCEPT_MODEL"] = "claude"
    with pytest.raises(SystemExit, match="CONCEPT_ALLOW_HOSTED"):
        concepts.model_from_config(pipeline)
