import io
import zipfile

from autoprof import fetch


def test_matches():
    assert fetch.matches("CSV", ["CSV"], {})
    assert fetch.matches("ZIP", ["SHP"], {"inner": "SHP"})
    assert fetch.matches("ZIP", ["ZIP"], {"inner": "CSV"})
    assert fetch.matches("JSONL", ["JSON"], {})
    assert fetch.matches("PXWEB", ["JSON", "PX"], {})
    assert fetch.matches("HTML", ["CSV"], {}) is False
    assert fetch.matches("CSV", [], {}) is None


def test_pick_member():
    assert fetch.pick_member(["readme.pdf", "x.dbf", "x.shp"]) == ("x.shp", "SHP")
    assert fetch.pick_member(["a.gpkg", "a.shp"]) == ("a.gpkg", "GPKG")
    assert fetch.pick_member(["__MACOSX/x.csv", "notes.pdf"]) == (None, None)


def test_zip_central_directory_from_tail(tmp_path):
    """A sparse file holding only the tail lists the members, as fetch does with a range request."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("big.bin", b"\0" * 200_000)
        z.writestr("layer.gpkg", b"x")
    data = buf.getvalue()
    sparse = tmp_path / "s.zip"
    fetch.sparse_file(sparse, len(data), data[-4096:])
    assert fetch.zip_members(sparse) == ["big.bin", "layer.gpkg"]


def test_line_cuts():
    assert fetch._nth_newline(bytearray(b"a\nb\nc\n"), 2) == 4
    assert fetch._turtle_cut(b"<a> <b> <c> .\n<d> <e> \"f") == b"<a> <b> <c> .\n"


def test_wfs_operation_url_from_capabilities():
    from lxml import etree
    from autoprof.fetch import operation_url, _xml_root
    caps = etree.fromstring(b'''<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
      xmlns:ows="http://www.opengis.net/ows/1.1" xmlns:xlink="http://www.w3.org/1999/xlink"><ows:OperationsMetadata>
      <ows:Operation name="GetFeature"><ows:DCP><ows:HTTP>
        <ows:Get xlink:href="https://map.example.org/proxy?server=a%20b&amp;"/></ows:HTTP></ows:DCP></ows:Operation>
      <ows:Operation name="DescribeFeatureType"><ows:DCP><ows:HTTP><ows:Get xlink:href=""/></ows:HTTP></ows:DCP>
      </ows:Operation></ows:OperationsMetadata></wfs:WFS_Capabilities>''')
    assert operation_url(caps, "GetFeature", "https://wfs.example.org", "?") == \
        ("https://map.example.org/proxy?server=a%20b", "&")
    assert operation_url(caps, "DescribeFeatureType", "https://wfs.example.org", "?") == ("https://wfs.example.org", "?")
    assert _xml_root(b"<?xml version='1.0'?>\n<wfs:FeatureCollection xmlns:wfs='http://www.opengis.net/wfs/2.0'>") \
        == "{http://www.opengis.net/wfs/2.0}FeatureCollection"
