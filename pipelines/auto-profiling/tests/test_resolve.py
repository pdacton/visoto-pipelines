from autoprof import resolve


def dist(iri, dataset, url, declared):
    return {"iri": iri, "dataset": dataset, "downloadURL": url, "accessURL": None, "declared": declared}


def test_opendatasoft_exports_group_with_parquet_representative():
    ds = "https://opendata.swiss/set/data/100158-kanton-basel-stadt"
    base = "https://data.bs.ch/api/v2/catalog/datasets/100158/exports/"
    dists = {f"d:{f}": dist(f"d:{f}", ds, base + f, t) for f, t in [
        ("csv?use_labels=true", ["CSV"]), ("parquet", ["PARQUET"]), ("json", ["JSON"]), ("kml", ["KML"]),
        ("turtle", ["RDF_TURTLE"]), ("n3", ["N3"]), ("rdfxml", ["RDF_XML"])]}
    groups = resolve.build_groups(dists)
    assert len(groups) == 2
    table = next(g for g in groups if g["representative"] == "d:parquet")
    rdf = next(g for g in groups if g is not table)
    assert set(table["members"]) == {"d:csv?use_labels=true", "d:parquet", "d:json", "d:kml"}
    assert rdf["representative"] == "d:turtle"
    assert "d:kml" not in table["candidates"]          # out of scope, never fetched


def test_pxweb_languages_group():
    ds = "https://opendata.swiss/set/data/241093"
    dists = {
        "de": dist("de", ds, "https://www.pxweb.bfs.admin.ch/pxweb/de/px-x-1/px-x-1/px-x-1.px", ["PX"]),
        "fr": dist("fr", ds, "https://www.pxweb.bfs.admin.ch/pxweb/fr/px-x-1/px-x-1/px-x-1.px", ["PX"]),
        "asset": dist("asset", ds, "https://www.bfs.admin.ch/asset/de/px-x-1", ["HTML", "PX"]),
    }
    groups = resolve.build_groups(dists)
    assert len(groups) == 1 and set(groups[0]["members"]) == {"de", "fr", "asset"}


def test_other_distributions_stay_apart():
    ds = "https://opendata.swiss/set/data/x"
    dists = {"a": dist("a", ds, "https://x.org/a.csv", ["CSV"]), "b": dist("b", ds, "https://x.org/b.csv", ["CSV"])}
    assert len(resolve.build_groups(dists)) == 2


def test_collect_merges_rows():
    rows = [
        {"dataset": "ds", "dist": "d", "download": "https://x.org/a.px", "format": "x", "media": "application/json"},
        {"dataset": "ds", "dist": "d", "download": "https://x.org/a.px", "format": "x", "media": "text/plain",
         "title": "A"},
    ]
    d = resolve.collect(rows)["d"]
    assert d["mediaTypes"] == ["application/json", "text/plain"]
    assert d["title"] == "A" and d["url"] == "https://x.org/a.px"
    assert d["declared"] == ["JSON", "PX"]


def test_read_datasets(tmp_path):
    f = tmp_path / "datasets.txt"
    f.write_text("# comment\n\nhttps://a.org/1  # trailing\n<https://a.org/2>\nhttps://a.org/1\n")
    assert resolve.read_datasets(f) == ["https://a.org/1", "https://a.org/2"]
