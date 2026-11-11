import duckdb

from cmatch import codematch, described, identifiers, lindas
from cmatch.codematch import Thresholds
from cmatch.registry import CANDIDATE, Registry, opaque_id
from conftest import AGE, AGG, MUNI, SEX


# --- lindas -----------------------------------------------------------------------------

def test_norm():
    assert lindas.norm("0261") == "261" and lindas.norm("261.0") == "261" and lindas.norm(" be ") == "BE"
    assert lindas.norm("") is None and lindas.norm(None) is None
    assert lindas.norm("12345678901234567890") == "12345678901234567890"


def test_split_scheme_and_level():
    c = lindas.CONCEPT
    assert lindas.split_scheme(c + "X/version/2024.1.0") == (c + "X", "X", "2024.1.0")
    assert lindas.split_scheme(c + "X") == (c + "X", "X", None)
    assert lindas.level_identity(c + "X/level_4/version/2024.1.0") == c + "X/level_4"


class FakeLindas:
    def __init__(self, schemes, codes):
        self._schemes, self._codes, self.fetched = schemes, codes, []

    def schemes(self):
        return [{"scheme": s, **dict(zip(("list", "id", "version"), lindas.split_scheme(s))),
                 "valid_from": None, "title_en": s, "title_de": None, "title_fr": None, "title_it": None}
                for s in self._schemes]

    def codes(self, scheme):
        self.fetched.append(scheme)
        return self._codes[scheme]


def test_refresh_fetches_only_changed_lists(tmp_path):
    c = lindas.CONCEPT
    con = lindas.connect(tmp_path / "codes.duckdb")
    fake = FakeLindas([c + "A", c + "B"], {c + "A": [("1", None)], c + "B": [("x", None)],
                                           c + "B/version/2": [("x", None), ("y", None)]})
    lindas.refresh(con, fake)
    assert sorted(fake.fetched) == [c + "A", c + "B"]
    fake.fetched.clear()
    lindas.refresh(con, fake)
    assert fake.fetched == []
    fake._schemes.append(c + "B/version/2")        # a new version: list B is fetched again, A is not
    lindas.refresh(con, fake)
    assert sorted(fake.fetched) == [c + "B", c + "B/version/2"]
    assert con.execute("SELECT COUNT(*) FROM codes").fetchall()[0][0] == 4


# --- identifiers ---------------------------------------------------------------------------

def test_identifier_validators():
    v = {x.name: x for x in identifiers.VALIDATORS}
    assert identifiers.ahv_valid("756.9217.0769.85") and not identifiers.ahv_valid("756.9217.0769.86")
    assert identifiers.uid_valid("CHE-116.281.710") and identifiers.uid_valid("CHE109322551 MWST")
    assert not identifiers.uid_valid("CHE-116.281.711")
    assert identifiers.egrid_valid("CH807306583219")
    # weak validators need the name
    assert v["egid"].applies("GWR_EGID", ["190", "1234567", "88"], 0.95)
    assert v["egid"].applies("TileWidth", ["256", "512", "1024"], 0.95) is None
    assert v["postcode"].applies("PLZ", ["3003", "8001", "1200"], 0.95)
    assert v["postcode"].applies("anzahl", ["3003", "8001", "1200"], 0.95) is None
    assert v["uid"].applies("x", ["CHE-116.281.710", "CHE-109.322.551", "nope"], 0.95) is None


# --- described ---------------------------------------------------------------------------

def test_described_keys():
    xsd = "http://www.w3.org/2001/XMLSchema#"
    assert described.key({"datatype": xsd + "date", "format": "%d.%m.%Y"})[0] == "date-dd.mm.yyyy"
    assert described.key({"datatype": xsd + "decimal", "unit": "http://qudt.org/vocab/unit/CCY_CHF"})[0] == \
        "decimal-CCY_CHF"
    assert described.key({"datatype": described.WKT, "container": {"geometryType": "MultiPolygon", "crs": "2056"}})[0] \
        == "geo-MultiPolygon-EPSG2056"
    assert described.key({"datatype": xsd + "string", "unit": "Anzahl"})[0] == "string"   # not a QUDT unit
    assert described.key({"datatype": None}) is None
    assert described.key({"datatype": xsd + "string", "nested": True}) is None


# --- code matching -------------------------------------------------------------------------

def run_match(pipeline, samples, **t):
    return codematch.match_all(pipeline.codes_db, samples, Thresholds(**t))


def test_unambiguous_municipalities_link_to_the_version_that_tells_them_apart(pipeline):
    r = run_match(pipeline, {"a": ["261", "351", "2196", "5586", "6621", "6623"]})["a"]
    assert r.automatic and r.automatic.list == MUNI and r.automatic.version == "2024"
    assert r.automatic.level == MUNI + "/level_2" and r.automatic.containment == 1.0


def test_values_valid_in_every_version_link_to_the_list(pipeline):
    r = run_match(pipeline, {"a": ["261", "351", "2196", "5586", "6621", "371"]})["a"]
    assert r.automatic and r.automatic.scheme == MUNI and r.automatic.version is None


def test_cantons_match_on_their_level(pipeline):
    r = run_match(pipeline, {"a": ["ZH", "be", "LU", "GE", "TI", "VS"]})["a"]
    assert r.automatic and r.automatic.level == MUNI + "/level_1"


def test_few_values_and_ambiguity_keep_candidates(pipeline):
    r = run_match(pipeline, {"a": ["1", "2"]})["a"]
    assert r.automatic is None and r.reason == "range-overlap"      # 1 and 2 fill their whole range in SEX
    assert {h.list for h in r.candidates} >= {SEX}
    # 261 and 351 are municipalities and agglomerations alike: no lead
    r = run_match(pipeline, {"b": ["261", "351"]}, min_distinct=2)["b"]
    assert r.automatic is None and r.reason == "ambiguous"
    assert {h.list for h in r.candidates if not h.dense} == {MUNI, AGG} and r.candidates[-1].list == AGE
    r = run_match(pipeline, {"c": ["261", "351", "371", "2196"]})["c"]
    assert r.automatic is None and r.reason == "few-values"


def test_dense_range_and_sequences_are_never_automatic(pipeline):
    r = run_match(pipeline, {"ids": [str(i) for i in range(1, 60)]})["ids"]
    assert r.automatic is None and r.reason == "dense-range"
    assert [h.list for h in r.candidates] == [AGE] and r.candidates[0].dense
    r = run_match(pipeline, {"seq": ["1", "2", "3", "4", "5"]})["seq"]
    assert r.automatic is None and r.reason == "range-overlap"


def test_dense_flag_set_for_age_hours(pipeline):
    con = duckdb.connect(str(pipeline.codes_db), read_only=True)
    rows = codematch.scores(con, {"x": ["700", "800", "900", "1000", "1100"]})["x"]
    dense = {r[0]: r[7] for r in rows}
    assert dense[AGE] is True


# --- registry ------------------------------------------------------------------------------

def test_registry_keeps_iris_and_creation_date(tmp_path):
    reg = Registry(tmp_path, "https://example.org/mds/")
    iri = reg.iri("objectclasses", opaque_id("objectclasses", "person", "fp"))
    reg.put("objectclasses", {"iri": iri, "id": "c-1", "title": {"en": "Person"}, "status": CANDIDATE})
    reg.entries["objectclasses"][iri]["created"] = "2026-01-01"
    reg.put("objectclasses", {"iri": iri, "id": "c-1", "title": {"en": "Natural person"}, "created": "2030-01-01"})
    reg.save()
    again = Registry.load(tmp_path, "https://example.org/mds/")
    e = again.get("objectclasses", iri)
    assert e["created"] == "2026-01-01" and e["title"]["en"] == "Natural person"
    assert opaque_id("objectclasses", "person", "fp") == opaque_id("objectclasses", "person", "fp")
