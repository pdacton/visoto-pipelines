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
    muni = {"new": {"title": {"en": "Municipality"}, "closeMatch": ["http://schema.org/AdministrativeArea"]}}
    pop = {"dataset": "https://example.org/population", "container": "main",
           "distributions": ["https://example.org/population/dist"]}
    bnd = {"dataset": "https://example.org/boundaries", "container": "gemeinden",
           "distributions": ["https://example.org/boundaries/dist"]}
    answers(pipeline, [
        # phase 3 format (per fingerprint): its property counts, its object class does not
        {"fingerprint": "fp-muni", "confidence": 0.95, "rationale": "Official municipality numbers.",
         "objectClass": {"new": {"title": {"en": "Person"}}},
         "property": {"new": {"title": {"en": "BFS municipality number"}, "closeMatch": ["http://schema.org/identifier"]}}},
        {"fingerprint": "fp-date", "none": True},
        # per table: the object class
        {"table": pop, "fingerprint": "fp-muni", "objectClass": muni, "confidence": 0.95},
        {"table": bnd, "fingerprint": "fp-muni", "objectClass": muni, "confidence": 0.95},
        {"table": bnd, "fingerprint": "fp-kt", "confidence": 0.9, "objectClass": muni,
         "property": {"new": {"title": {"en": "canton"}}},
         "codeList": "https://example.org/mds/valuedomain/SEX"},             # contradicted by the values
        {"table": pop, "fingerprint": "fp-pop", "confidence": 0.5,             # below the threshold: candidate only
         "objectClass": muni, "property": {"new": {"title": {"en": "population"}}}},
    ])
    run_all(pipeline)
    links = links_by_slot(pipeline)
    reg = Registry.load(pipeline.registry_dir, pipeline.base_iri)
    a, b = links[slots[0]["iri"]], links[slots[2]["iri"]]
    assert a["dataElementConcept"] and a["dataElementConcept"] == b["dataElementConcept"]
    assert [e["title"]["en"] for e in reg.all("objectclasses")] == ["Municipality"]   # created once; no Person
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
    before = {f.name: f.read_text() for f in pipeline.registry_dir.glob("*.jsonl")}
    (pipeline.pipeline_dir / "answers" / "test.jsonl").unlink()      # the cache answers now
    run_all(pipeline)
    after = {f.name: f.read_text() for f in pipeline.registry_dir.glob("*.jsonl")}
    assert after == before                                            # byte for byte: no entry, no field changes
    assert links_by_slot(pipeline)[slots[0]["iri"]]["dataElementConcept"] == a["dataElementConcept"]


def test_unanswered_fingerprints_become_requests(pipeline):
    write_slots(pipeline, slots_v1())
    run_all(pipeline)
    reqs = [json.loads(l) for l in (pipeline.out / "concept-requests.jsonl").read_text().splitlines()]
    assert len(reqs) == 3                                       # one per table
    assert {c["fingerprint"] for r in reqs for c in r["ask"]} == {s["fingerprint"] for s in slots_v1()}
    bnd = next(r for r in reqs if r["table"]["dataset"] == "https://example.org/boundaries")
    assert [c["name"] for c in bnd["columns"]] == ["BFS_Nr", "Kanton"]          # the whole table
    muni = next(c for c in bnd["ask"] if c["fingerprint"] == "fp-muni")
    assert muni["name"] == "BFS_Nr" and muni["valueDomain"] and "nearestProperties" in muni


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
        """Answers the asked columns it has a reply for; refuses a table with none."""
        self.requests.append(kw)
        req = json.loads(kw["messages"][0]["content"])
        cols = [{"fingerprint": c["fingerprint"], **self.replies[c["fingerprint"]]}
                for c in req["ask"] if c["fingerprint"] in self.replies]
        return FakeResponse({"columns": cols}) if cols else FakeResponse({}, stop="refusal")


def part(title=None, iri=None):
    return {"iri": iri, "title": title, "description": f"The {title}." if title else None, "closeMatch": []}


def test_claude_model_with_a_fake_client(pipeline):
    slots = slots_v1()
    write_slots(pipeline, slots)
    seed.run(pipeline)
    confirm.run(pipeline)
    linkvalues.run(pipeline)
    client = FakeClient({
        "fp-muni": {"none": False, "objectClass": part("Municipality"), "property": part("BFS municipality number"),
                    "codeList": None, "confidence": 0.93, "rationale": "Official numbers."},
        "fp-date": {"none": True, "objectClass": part(), "property": part(), "codeList": None,
                    "confidence": 0.9, "rationale": "Layout column."},
    })
    model = concepts.ClaudeModel(client=client)
    reg = Registry.load(pipeline.registry_dir, pipeline.base_iri)
    linker = concepts.Linker(pipeline, reg, model)
    links = {r["slot"]: r for r in linker.link(slots, linkvalues.read(pipeline))}
    assert links[slots[0]["iri"]]["dataElementConcept"] == links[slots[2]["iri"]]["dataElementConcept"]
    assert {"concept": "none"} in links[slots[5]["iri"]]["notes"]
    # one call per table; what is not answered stays a request (population: Einwohner; boundaries: Kanton;
    # buildings: GWR_EGID)
    assert model.calls == 3 and len(linker.requests) == 3
    assert sorted(c["name"] for r in linker.requests for c in r["ask"]) == ["Einwohner", "GWR_EGID", "Kanton"]
    req = client.requests[0]
    assert req["output_config"]["format"]["schema"] == concepts.ANSWER_SCHEMA and req["fallbacks"] == "default"


def test_claude_model_needs_explicit_permission(pipeline):
    import pytest
    pipeline.values["CONCEPT_MODEL"] = "claude"
    with pytest.raises(SystemExit, match="CONCEPT_ALLOW_HOSTED"):
        concepts.model_from_config(pipeline)


# --- phase 3b: object class per column in its table ----------------------------------------

PERSONS = "https://example.org/persons"


def persons_table():
    """A denormalised table: persons with their municipality of residence and that municipality's name."""
    st = "https://example.org/sp"
    slots = [slot("person_id", [f"P{i}" for i in range(6)], dataset=PERSONS, type_="string", fingerprint="fp-pid",
                  structure=st),
             slot("wohngemeinde_bfs", MUNI_VALUES, dataset=PERSONS, fingerprint="fp-wg", structure=st),
             slot("gemeinde_name", ["Zürich", "Bern", "Rapperswil-Jona", "Le Chenit", "Uster", "Biel/Bienne"],
                  dataset=PERSONS, type_="string", fingerprint="fp-gn", structure=st),
             slot("alter", ["23", "45", "67", "31", "52"], dataset=PERSONS, fingerprint="fp-age", structure=st)]
    record = {"iri": slots[0]["container"]["iri"], "path": "main",
              "dataset": {"iri": PERSONS, "title": {"de": "Personen", "fr": "Personnes"},
                          "description": {"de": "Personen und ihre Wohngemeinde."}},
              "distribution": {"iri": PERSONS + "/dist", "title": "Personen CSV"},
              "columns": [{"name": s["name"], "datatype": s["datatype"], "pattern": None} for s in slots],
              "candidateKeys": ["person_id"],
              "dependencies": [{"determinant": "wohngemeinde_bfs", "dependents": ["gemeinde_name"], "rows": 600,
                                "distinct": 6},
                               {"determinant": "gemeinde_name", "dependents": ["wohngemeinde_bfs"], "rows": 600,
                                "distinct": 6}]}
    return slots, record


def write_containers(cfg, records):
    with open(cfg.raw / "containers.jsonl", "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def new(title):
    return {"new": {"title": {"en": title}}}


class CountingModel:
    """Answers every asked column from a table → {fingerprint: (object class, property)} map."""

    def __init__(self, plan):
        self.plan, self.calls, self.requests = plan, 0, []

    def answer(self, request):
        self.calls += 1
        self.requests.append(request)
        key = (request["table"]["dataset"], request["table"]["container"])
        cols = []
        for c in request["ask"]:
            oc, prop = self.plan.get(key, {}).get(c["fingerprint"], ("Thing", c["name"]))
            cols.append({"fingerprint": c["fingerprint"], "objectClass": new(oc), "property": new(prop),
                         "codeList": None, "confidence": 0.9, "rationale": f"{c['name']}: {prop} of {oc}"})
        return {"columns": cols}


def link_with(pipeline, slots, model):
    seed.run(pipeline)
    confirm.run(pipeline)
    linkvalues.run(pipeline)
    reg = Registry.load(pipeline.registry_dir, pipeline.base_iri)
    linker = concepts.Linker(pipeline, reg, model)
    from cmatch import slots as slotio
    links = linker.link(slots, linkvalues.read(pipeline), slotio.load_containers(pipeline))
    return {r["slot"]: r for r in links}, reg, linker


def object_class_of(reg, rec):
    dec = reg.get("dataelementconcepts", rec["dataElementConcept"])
    return reg.get("objectclasses", dec["objectClass"])["title"]["en"]


def test_denormalised_table_gets_two_object_classes(pipeline):
    slots, record = persons_table()
    write_slots(pipeline, slots)
    write_containers(pipeline, [record])
    model = CountingModel({(PERSONS, "main"): {
        "fp-pid": ("Person", "identifier"), "fp-wg": ("Person", "municipality of residence"),
        "fp-gn": ("Municipality", "name"), "fp-age": ("Person", "age")}})
    links, reg, _ = link_with(pipeline, slots, model)
    oc = {s["name"]: object_class_of(reg, links[s["iri"]]) for s in slots}
    assert oc == {"person_id": "Person", "wohngemeinde_bfs": "Person", "gemeinde_name": "Municipality",
                  "alter": "Person"}
    # the model saw the whole table once, with dataset context and dependencies
    [req] = model.requests
    assert req["datasetContext"]["title"] == {"de": "Personen", "fr": "Personnes"}
    assert req["distributionTitle"] == "Personen CSV" and req["candidateKeys"] == ["person_id"]
    assert req["dependencies"][0]["determinant"] == "wohngemeinde_bfs"
    assert [c["name"] for c in req["ask"]] == [s["name"] for s in slots]
    # the table's own entity: gemeinde_name (another entity's attribute) does not vote
    main = concepts.main_object_classes(list(links.values()), slots, reg, {record["iri"]: record})
    assert reg.get("objectclasses", main[record["iri"]])["title"]["en"] == "Person"


def test_same_geometry_column_in_two_tables_gets_different_object_classes(pipeline):
    geom = dict(type_="string", datatype="http://www.opengis.net/ont/geosparql#wktLiteral", fingerprint="fp-geom")
    a = slot("geom", [], dataset="https://example.org/buildings", structure="https://example.org/s5", **geom)
    b = slot("geom", [], dataset="https://example.org/groundwater", structure="https://example.org/s6", **geom)
    write_slots(pipeline, [a, b])
    model = CountingModel({("https://example.org/buildings", "main"): {"fp-geom": ("Building", "geometry")},
                           ("https://example.org/groundwater", "main"): {"fp-geom": ("Groundwater body", "geometry")}})
    links, reg, _ = link_with(pipeline, [a, b], model)
    assert object_class_of(reg, links[a["iri"]]) == "Building"
    assert object_class_of(reg, links[b["iri"]]) == "Groundwater body"
    pa = reg.get("dataelementconcepts", links[a["iri"]]["dataElementConcept"])["property"]
    pb = reg.get("dataelementconcepts", links[b["iri"]]["dataElementConcept"])["property"]
    assert pa == pb                                    # one property, two object classes
    # the second table only asked for the object class: the property was known from the first
    assert "knownProperty" in model.requests[1]["ask"][0]


def test_same_container_name_in_two_structures_of_one_dataset_are_two_tables(pipeline):
    """Every CSV of a dataset has a `main`: the distributions tell the tables apart."""
    a = slot("geom", [], dataset=PERSONS, distributions=[PERSONS + "/csv1"], structure="https://example.org/s8",
             type_="string", fingerprint="fp-g")
    b = slot("geom", [], dataset=PERSONS, distributions=[PERSONS + "/csv2"], structure="https://example.org/s9",
             type_="string", fingerprint="fp-g")
    write_slots(pipeline, [a, b])
    model = CountingModel({})
    link_with(pipeline, [a, b], model)
    assert model.calls == 2
    assert [r["table"]["distributions"] for r in model.requests] in ([[PERSONS + "/csv1"], [PERSONS + "/csv2"]],
                                                                    [[PERSONS + "/csv2"], [PERSONS + "/csv1"]])


def test_edited_dataset_description_makes_no_model_call(pipeline):
    slots, record = persons_table()
    write_slots(pipeline, slots)
    write_containers(pipeline, [record])
    first = CountingModel({})
    link_with(pipeline, slots, first)
    assert first.calls == 1
    record["dataset"]["description"] = {"de": "Neu beschrieben.", "en": "Described anew."}
    record["distribution"]["title"] = "Personen 2026"
    write_containers(pipeline, [record])
    again = CountingModel({})
    links, _, linker = link_with(pipeline, slots, again)
    assert again.calls == 0 and linker.requests == []
    assert all(links[s["iri"]].get("dataElementConcept") for s in slots)


def test_code_column_and_label_column_of_one_list_share_the_value_domain(pipeline):
    from conftest import CANTON_NAMES
    codes = list(CANTON_NAMES)[:10]
    a = slot("kanton_kz", codes, type_="string", fingerprint="fp-kz", structure="https://example.org/s7")
    b = slot("kanton_name", [CANTON_NAMES[c][0] for c in codes], type_="string", fingerprint="fp-kn",
             structure="https://example.org/s7")
    write_slots(pipeline, [a, b])
    run_all(pipeline)
    links = links_by_slot(pipeline)
    assert links[a["iri"]]["valueDomain"] == links[b["iri"]]["valueDomain"]
    assert links[a["iri"]]["valueDomain"].endswith("/valuedomain/GDE")
    how = {s["name"]: next(m for m in links[s["iri"]]["matches"] if m["kind"] == "valueDomain")["evidence"]
           for s in (a, b)}
    assert how["kanton_kz"]["matched"] == "notation" and how["kanton_name"]["matched"] == "label"
    g = output_graph(pipeline)
    assert {str(o) for o in g.objects(None, AP.matchedOn)} >= {"notation", "label"}
