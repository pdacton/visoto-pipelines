from autoprof import formats


def test_px_json_conflict_is_kept():
    # PxWeb API link declared as JSON: the URL says PX
    declared = formats.declared_types(
        [], ["application/json"],
        ["https://etab.llv.li/PXWEb/api/v1/de/eTab//Bevölkerung/Haushalte,%20Familien/251.501d.px"])
    assert declared == ["JSON", "PX"]


def test_csv_xls_conflict_is_kept():
    declared = formats.declared_types(
        ["http://publications.europa.eu/resource/authority/file-type/CSV"],
        ["http://www.iana.org/assignments/media-types/application/vnd.ms-excel"], ["https://example.org/data"])
    assert declared == ["CSV", "XLS"]


def test_format_literal_forms():
    assert formats.from_format("http://publications.europa.eu/resource/authority/file-type/WFS_SRVC") == "WFS"
    assert formats.from_format("gpkg") == "GPKG"
    assert formats.from_format("CSV") == "CSV"
    assert formats.from_format("http://publications.europa.eu/resource/authority/file-type/UNSPECIFIED") is None
    assert formats.from_format("https://en.wikipedia.org/wiki/Uniform_Resource_Identifier") is None
    assert formats.from_media_type("https://www.iana.org/assignments/media-types/text/csv") == "CSV"
    assert formats.from_media_type("application/xls") == "XLS"


def test_url_hints():
    assert formats.from_url("https://data.bs.ch/api/v2/catalog/datasets/100158/exports/parquet") == "PARQUET"
    assert formats.from_url("https://ge.ch/sitg/geodata/SITG/OPENDATA/DPS_FORTIFICATIONS-SHP.zip") == "SHP"
    assert formats.from_url("https://files.geo.so.ch/x/aktuell/x.gpkg.zip") == "GPKG"
    assert formats.from_url("https://files.geo.so.ch/x/aktuell/x.xtf.zip") == "INTERLIS"
    assert formats.from_url("https://geo.ur.ch/wfs?request=getCapabilities") == "WFS"
    assert formats.from_url("https://example.org/a?service=WFS&request=GetCapabilities") == "WFS"
    assert formats.from_url("https://www.bfs.admin.ch/asset/de/px-x-0602050000_102") == "PX"
    assert formats.from_url("https://example.org/download/245") is None


def test_redundant_container_dropped():
    assert formats.declared_types(["ZIP"], [], ["https://x.org/a-SHP.zip"]) == ["SHP"]


def test_worth_fetching():
    assert formats.worth_fetching([])
    assert formats.worth_fetching(["HTML", "PX"])
    assert not formats.worth_fetching(["WMS"])
    assert not formats.worth_fetching(["HTML", "PDF"])


def test_pxweb_api():
    bfs = "https://www.pxweb.bfs.admin.ch/pxweb/de/px-x-0602050000_102/px-x-0602050000_102/px-x-0602050000_102.px"
    assert formats.pxweb_api(bfs) == \
        "https://www.pxweb.bfs.admin.ch/api/v1/de/px-x-0602050000_102/px-x-0602050000_102.px"
    assert formats.pxweb_api("https://www.bfs.admin.ch/asset/fr/px-x-0602050000_102") == \
        "https://www.pxweb.bfs.admin.ch/api/v1/fr/px-x-0602050000_102/px-x-0602050000_102.px"
    llv = "https://etab.llv.li/PXWEb/pxweb/en/eTab/etab__Bildung__Berufliche%20Grundbildung/483.011.px"
    assert formats.pxweb_api(llv) == "https://etab.llv.li/PXWEb/api/v1/en/eTab/Bildung/Berufliche%20Grundbildung/483.011.px"
    assert formats.pxweb_api("https://example.org/data.csv") is None


def test_families_and_eu_iris():
    assert formats.family("PARQUET") == "tabular"
    assert formats.family("WFS") == "geo"
    assert formats.family("PXWEB") == "px"
    assert formats.eu_iri("WFS").endswith("/WFS_SRVC")
    assert formats.eu_iri("PX") is None


def test_env_file_defaults(tmp_path, monkeypatch):
    from autoprof.config import read_env_file
    f = tmp_path / "pipeline.env"
    f.write_text('NAME=x\nLABEL="A label"\nDATASETS=${DATASETS:-datasets.txt}\n# C=1\n')
    monkeypatch.delenv("DATASETS", raising=False)
    assert read_env_file(f) == {"NAME": "x", "LABEL": "A label", "DATASETS": "datasets.txt"}
    monkeypatch.setenv("DATASETS", "datasets-large.txt")
    assert read_env_file(f)["DATASETS"] == "datasets-large.txt"
