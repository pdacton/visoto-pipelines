import json
import shutil
from pathlib import Path

import pytest

from autoprof.engines import NotTabular, px, tabular, tree
from autoprof.sniff import encoding, sniff
from conftest import FIXTURES


def csv_profile(cfg, tmp_path, name="bevoelkerung.csv"):
    path = FIXTURES / name
    head = path.read_bytes()
    _, detail = sniff(head)
    detail["encoding"] = encoding(head)
    return tabular.profile(path, "CSV", cfg, tmp_path, detail)


def test_tabular_csv_bevoelkerung(cfg, tmp_path):
    [part] = csv_profile(cfg, tmp_path)
    fields = {f.name: f for f in part.fields}
    assert part.dialect["delimiter"] == ";" and part.dialect["header"] is True
    assert part.rowCount == 60
    # DuckDB's dd.mm.yyyy date wins over Frictionless's string
    assert fields["Stichtag"].type == "date"
    assert fields["BFS_Nr"].type == "integer" and fields["Einwohner"].type == "integer"
    assert fields["Flaeche_km2"].type == "number"
    # "..." is a missing value, not a string
    assert fields["Anteil_Auslaender_%"].type == "number"
    assert fields["Anteil_Auslaender_%"].stats["nullPercentage"] > 0
    assert fields["Kanton"].categorical and fields["Kanton"].stats["values"] == ["BE", "FR", "GE", "VD", "ZH"]
    assert fields["Hauptort"].booleanCandidate
    assert part.keysUnique and part.is_cube()
    keys = {f.name for f in part.key_fields()}
    assert keys == {"BFS_Nr", "Gemeinde", "Kanton", "Stichtag", "Hauptort"}


def test_tabular_cp1252_csv(cfg, tmp_path):
    src = tmp_path / "latin.csv"
    src.write_bytes("Ort;Wert\nZürich;1\nGenève;2\nBern;3\n".encode("cp1252"))
    head = src.read_bytes()
    _, detail = sniff(head)
    detail["encoding"] = encoding(head)
    [part] = tabular.profile(src, "CSV", cfg, tmp_path / "t", detail)
    assert part.dialect["encoding"] == "cp1252"
    assert "Zürich" in part.fields[0].stats["values"]


def test_spreadsheet_header_detection():
    rows = [["Bevölkerung 2023", None, None], [None, None, None],
            ["Kanton", "Einwohner", None], ["Total", "Männer", "Frauen"], ["ZH", 1, 2], ["BE", 3, 4]]
    assert tabular.find_header(rows) == (2, 2)
    assert tabular.find_header([["a", "b"], [1, 2]]) == (0, 1)


def test_sheet_to_csv_merged_header(tmp_path):
    rows = [["Titel", None, None], ["Kanton", "Bevölkerung", None], [None, "Männer", "Frauen"],
            ["ZH", 1, 2], ["BE", 3, 4], [None, None, None], ["Quelle: BFS", None, None]]
    out = tmp_path / "s.csv"
    found = tabular.sheet_to_csv(rows, out)
    lines = out.read_text().splitlines()
    assert found == {"skipRows": 1, "headerRowCount": 2}
    assert lines[0] == "Kanton,Bevölkerung / Männer,Bevölkerung / Frauen"
    assert lines[1:] == ["ZH,1,2", "BE,3,4"]          # the footnote after the blank row is dropped


def test_xlsx_sheets(cfg, tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Daten"
    ws.append(["Jahr", "Wert"])
    for y in range(2000, 2010):
        ws.append([y, y * 1.5])
    wb.create_sheet("Leer")
    path = tmp_path / "w.xlsx"
    wb.save(path)
    [part] = tabular.profile(path, "XLSX", cfg, tmp_path / "t", {})
    assert part.label == "Daten" and part.slug == "main"
    assert [f.type for f in part.fields] == ["integer", "number"]


def test_json_records_and_not_tabular(cfg, tmp_path):
    src = tmp_path / "r.json"
    src.write_text(json.dumps({"exportDate": "x", "data": [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]}))
    [part] = tabular.profile(src, "JSON", cfg, tmp_path / "t", {})
    assert part.dialect == {"recordsPath": "/data"} and [f.type for f in part.fields] == ["integer", "string"]
    with pytest.raises(NotTabular):
        tabular.profile(FIXTURES / "nested.json", "JSON", cfg, tmp_path / "u", {})


def test_tree_nested_json(cfg, tmp_path):
    [part] = tree.profile(FIXTURES / "nested.json", "JSON", cfg, tmp_path, {})
    fields = {f.name: f for f in part.fields}
    layers = fields["layers"]
    assert layers.maxCount is None and layers.node is not None
    inner = {f.name: f for f in layers.node.fields}
    assert inner["id"].minCount == 1 and inner["minzoom"].minCount == 0
    assert inner["paint"].node is not None
    assert fields["sources"].node.fields[0].name == "base"


def test_tree_xml(cfg, tmp_path):
    [part] = tree.profile(FIXTURES / "records.xml", "XML", cfg, tmp_path, {})
    data = next(f for f in part.fields if f.name == "data")
    assert data.maxCount is None and data.stats["maxItems"] == 3
    inner = {f.name: f for f in data.node.fields}
    assert inner["@id"].type == "integer" and inner["@id"].minCount == 1
    assert inner["datum"].type == "date"
    assert inner["notiz"].minCount == 0
    assert inner["anzahl"].type == "integer"


def test_px_from_pxweb(tmp_path):
    d = tmp_path / "t.pxweb"
    d.mkdir()
    shutil.copy(FIXTURES / "pxweb-meta-de.json", d / "meta-de.json")
    shutil.copy(FIXTURES / "pxweb-meta-fr.json", d / "meta-fr.json")
    shutil.copy(FIXTURES / "table.px", d / "keywords.px")
    [part] = px.profile(d, "PXWEB", None, tmp_path, {})
    assert part.is_cube() and part.rowCount == 4
    fields = {f.name: f for f in part.fields}
    assert fields["Jahr"].type == "year" and fields["Jahr"].role == "key"
    assert fields["Kanton"].codeLabels["1"] == {"de": "Zürich", "fr": "Zurich"}
    value = fields["value"]
    assert value.role == "measure" and value.type == "integer"       # DECIMALS=0
    assert value.unit == "http://qudt.org/vocab/unit/NUM"            # UNITS="Personen"


def test_px_file(tmp_path):
    [part] = px.profile(FIXTURES / "table.px", "PX", None, tmp_path, {})
    fields = {f.name: f for f in part.fields}
    assert set(fields) == {"Jahr", "Kanton", "value"}
    assert fields["Kanton"].constraints["enum"] == ["0", "1"]
    assert fields["Jahr"].stats.get("isTime")


def test_tree_counts_array_items_as_parents(cfg, tmp_path):
    [part] = tree.profile(FIXTURES / "nested.json", "JSON", cfg, tmp_path, {})
    layers = next(f for f in part.fields if f.name == "layers")
    inner = {f.name: f for f in layers.node.fields}
    assert inner["id"].stats["count"] == 3 and inner["id"].stats["nullPercentage"] == 0
    assert round(inner["minzoom"].stats["nullPercentage"]) == 33
    assert all(0 <= f.stats["nullPercentage"] <= 100 for f in layers.node.fields)


def test_tree_xml_types_from_xsd(cfg, tmp_path):
    xml = tmp_path / "s.xml"
    shutil.copy(FIXTURES / "records.xml", xml)
    (tmp_path / "s.xml.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="titel" type="xs:string"/><xs:element name="anzahl" type="xs:decimal"/>'
        '</xs:schema>')
    [part] = tree.profile(xml, "XML", cfg, tmp_path, {})
    data = next(f for f in part.fields if f.name == "data")
    inner = {f.name: f for f in data.node.fields}
    assert inner["anzahl"].type == "number"        # the XSD wins over the inferred integer
