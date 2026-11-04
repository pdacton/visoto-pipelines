import io
import struct
import zipfile

import pytest

from autoprof.sniff import csv_dialect, encoding, sniff


def zip_bytes(entries: dict, first_stored=False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data, compress_type=zipfile.ZIP_STORED if first_stored else zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def xlsx_bytes() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["a", "b"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def ole_xls_head() -> bytes:
    """An OLE2 header whose directory (sector 0) names a Workbook stream."""
    header = bytearray(512)
    header[:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    header[30:32] = struct.pack("<H", 9)              # 512-byte sectors
    header[48:52] = struct.pack("<I", 0)              # directory starts at sector 0
    directory = "Root Entry".encode("utf-16-le").ljust(128, b"\0") + "Workbook".encode("utf-16-le")
    return bytes(header) + directory.ljust(512, b"\0")


@pytest.mark.parametrize("head, token", [
    (b"PAR1\x15\x04", "PARQUET"),
    (b"SQLite format 3\x00" + b"\0" * 52 + b"GPKG" + b"\0" * 28, "GPKG"),
    (b"SQLite format 3\x00" + b"\0" * 80, "SQLITE"),
    (b"%PDF-1.7\n", "PDF"),
    (b'CHARSET="ANSI";\nAXIS-VERSION="2010";\nLANGUAGE="de";\n', "PX"),
    (b"<!DOCTYPE html><html><head><title>Login</title>", "HTML"),
    (b"<html lang='de'><body>Not found</body></html>", "HTML"),
    (b'<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">', "RDF_XML"),
    (b'<?xml version="1.0"?><wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
     b'xmlns:gml="http://www.opengis.net/gml/3.2">', "GML"),
    (b'<gml:FeatureCollection xmlns:gml="http://www.opengis.net/gml">', "GML"),
    (b'<wfs:WFS_Capabilities version="2.0.0" xmlns:wfs="http://www.opengis.net/wfs/2.0">', "WFS"),
    (b'<?xml version="1.0"?>\n<!-- c --><ObjectNode><exportDate>x</exportDate>', "XML"),
    (b'{"@context": "https://schema.org/", "@type": "Dataset"}', "JSON_LD"),
    (b'{"type": "FeatureCollection", "features": []}', "GEOJSON"),
    (b'{"title":"T","variables":[{"code":"Jahr","values":["0"],"valueTexts":["1995"]}]}', "PXWEB"),
    (b'{"a": 1}\n{"a": 2}\n{"a": 3}\n', "JSONL"),
    (b'[{"a": 1}, {"a": 2}]', "JSON"),
    (b"@prefix ex: <http://ex.org/> .\nex:a ex:b ex:c .\n", "RDF_TURTLE"),
    (b"<http://ex.org/a> <http://ex.org/b> \"c\" .\n<http://ex.org/a> <http://ex.org/b> <http://ex.org/d> .\n", "NT"),
    (b"\xef\xbb\xbfBFS_Nr;Gemeinde;Einwohner\n351;Bern;90445\n261;Z\xc3\xbcrich;246894\n", "CSV"),
    (b"a\tb\tc\n1\t2\t3\n4\t5\t6\n", "TSV"),
    (b"just some words\nwithout any columns\n", "TXT"),
])
def test_content_rules(head, token):
    assert sniff(head)[0] == token


def test_n3_by_content_type():
    assert sniff(b"@prefix ex: <http://ex.org/> .\n", "text/n3")[0] == "N3"


def test_zip_family():
    assert sniff(xlsx_bytes())[0] == "XLSX"
    ods = zip_bytes({"mimetype": "application/vnd.oasis.opendocument.spreadsheet", "content.xml": "<x/>"},
                    first_stored=True)
    assert sniff(ods)[0] == "ODS"
    token, detail = sniff(zip_bytes({"kunstbaute.shp": b"x", "kunstbaute.dbf": b"y"}))
    assert token == "ZIP" and detail["firstEntry"] == "kunstbaute.shp"


def test_ole_workbook():
    assert sniff(ole_xls_head())[0] == "XLS"


def test_empty():
    assert sniff(b"") == (None, {"reason": "empty"})


def test_csv_dialect_and_encoding():
    d = csv_dialect("a;b;c\n1;2;3\n4;5;6\n7;8;")
    assert d["delimiter"] == ";"
    assert csv_dialect("one column\nonly\nhere\n") is None
    assert encoding("Zürich".encode("cp1252")) == "cp1252"
    assert encoding(b"\xef\xbb\xbfa;b") == "utf-8-sig"
    assert encoding("Zürich".encode()) == "utf-8"
