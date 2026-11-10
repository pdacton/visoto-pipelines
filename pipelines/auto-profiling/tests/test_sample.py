from autoprof import sample


def slot(name, values, type="integer", categorical=False):
    return {"name": name, "sample": values, "type": type, "categorical": categorical}


def test_cases_from_names_and_values():
    assert "municipality-code" in sample.cases(slot("BFS_Nr", ["261", "351", "5586"]))
    assert "municipality-code" not in sample.cases(slot("gemeinde_name", ["261", "351", "5586"]))
    assert "canton-code" in sample.cases(slot("Kanton", ["BE", "ZH", "GE"], "string"))
    assert "identifier" in sample.cases(slot("GWR_EGID", ["1234567", "190"]))
    assert "identifier" not in sample.cases(slot("TileWidth", ["256", "512"]))
    assert "identifier" in sample.cases(slot("unternehmen", ["CHE-123.456.789", "CHE-109.322.551"], "string"))
    assert "labels-not-codes" in sample.cases(slot("ort", ["Bern", "Zürich", "Genève", "x"], "string"))
    assert "small-int-code" in sample.cases(slot("status", ["1", "2", "3"], categorical=True))


def test_selection_is_deterministic_and_respects_caps():
    ds = {f"https://example.org/d{i}": {"engines": {"geo" if i % 2 else "tabular"}, "slots": 10,
                                         "cases": {"canton-code"} if i % 7 == 0 else set(),
                                         "hosts": {f"h{i % 4}"}, "names": {"x"}} for i in range(60)}
    a, why = sample.select(ds, 15)
    assert a == sample.select(dict(reversed(list(ds.items()))), 15)[0]
    assert len(a) == 15
    hosts = [min(ds[i]["hosts"]) for i in a]
    assert max(hosts.count(h) for h in set(hosts)) <= sample.PER_HOST
    assert sum(1 for i in a if "canton-code" in ds[i]["cases"]) >= min(sample.CASES["canton-code"], 9)
