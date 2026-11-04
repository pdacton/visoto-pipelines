"""Format tokens: declared types from DCAT metadata, families and EU file-type IRIs.

A token is an EU file-type code where one exists (CSV, RDF_TURTLE, ...), with
the service suffix dropped (WFS, not WFS_SRVC), plus a few of our own (PX,
PXWEB, JSONL).
"""
import re
from urllib.parse import parse_qs, quote, unquote, urlparse, urlunparse

EU_FILE_TYPE = "http://publications.europa.eu/resource/authority/file-type/"

# EU file-type code → token, where they differ
EU_ALIASES = {
    "WFS_SRVC": "WFS", "WMS_SRVC": "WMS", "WMTS_SRVC": "WMTS", "GEOTIFF": "TIFF",
    "SPARQLQ": "SPARQL", "MAP_PRVW": "HTML", "XHTML": "HTML", "TXT": "TXT",
    "RDF_N_TRIPLES": "NT", "JSON_LD": "JSON_LD", "RDF": "RDF_XML", "UNSPECIFIED": None,
}
# token → EU file-type code, for tokens with an EU equivalent
TO_EU = {
    "CSV": "CSV", "TSV": "TSV", "XLSX": "XLSX", "XLS": "XLS", "ODS": "ODS", "PARQUET": "PARQUET",
    "JSON": "JSON", "GEOJSON": "GEOJSON", "XML": "XML", "GML": "GML", "SHP": "SHP", "GPKG": "GPKG",
    "WFS": "WFS_SRVC", "RDF_TURTLE": "RDF_TURTLE", "N3": "N3", "RDF_XML": "RDF_XML",
    "JSON_LD": "JSON_LD", "NT": "RDF_N_TRIPLES", "ZIP": "ZIP", "HTML": "HTML", "PDF": "PDF",
    "KML": "KML", "GPX": "GPX", "TXT": "TXT",
}

# Free-text dct:format literals and media types → token
FREE_TEXT = {
    "CSV": "CSV", "TSV": "TSV", "XLSX": "XLSX", "XLS": "XLS", "EXCEL": "XLSX", "ODS": "ODS",
    "PARQUET": "PARQUET", "JSON": "JSON", "JSONL": "JSONL", "GEOJSON": "GEOJSON", "XML": "XML",
    "GML": "GML", "SHP": "SHP", "SHAPEFILE": "SHP", "ESRI SHAPEFILE": "SHP", "GPKG": "GPKG",
    "GEOPACKAGE": "GPKG", "WFS": "WFS", "WMS": "WMS", "WMTS": "WMTS", "PX": "PX", "PC-AXIS": "PX",
    "RDF": "RDF_XML", "TTL": "RDF_TURTLE", "TURTLE": "RDF_TURTLE", "N3": "N3", "JSON-LD": "JSON_LD",
    "JSONLD": "JSON_LD", "ZIP": "ZIP", "HTML": "HTML", "PDF": "PDF", "KML": "KML", "GPX": "GPX",
    "TIFF": "TIFF", "DXF": "DXF", "API": "REST", "GDB": "GDB", "FEATHER": "FEATHER", "TXT": "TXT",
}
MEDIA_TYPES = {
    "text/csv": "CSV", "text/tab-separated-values": "TSV",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
    "application/vnd.ms-excel": "XLS", "application/xls": "XLS", "application/x-xls": "XLS",
    "application/vnd.oasis.opendocument.spreadsheet": "ODS",
    "application/parquet": "PARQUET", "application/vnd.apache.parquet": "PARQUET",
    "application/json": "JSON", "application/x-ndjson": "JSONL", "application/jsonl": "JSONL",
    "application/geo+json": "GEOJSON", "application/vnd.geo+json": "GEOJSON",
    "application/xml": "XML", "text/xml": "XML", "application/gml+xml": "GML",
    "application/zip": "ZIP", "application/x-zip-compressed": "ZIP",
    "application/geopackage+sqlite3": "GPKG", "application/x-shapefile": "SHP",
    "text/turtle": "RDF_TURTLE", "text/n3": "N3", "application/rdf+xml": "RDF_XML",
    "application/ld+json": "JSON_LD", "application/n-triples": "NT",
    "text/html": "HTML", "application/xhtml+xml": "HTML", "application/pdf": "PDF",
    "application/vnd.google-earth.kml+xml": "KML", "application/gpx+xml": "GPX",
    "image/tiff": "TIFF", "image/jpeg": "JPEG", "image/png": "PNG", "text/plain": "TXT",
    "application/sparql-query": "SPARQL",
}
EXTENSIONS = {
    "csv": "CSV", "tsv": "TSV", "xlsx": "XLSX", "xlsm": "XLSX", "xls": "XLS", "ods": "ODS",
    "parquet": "PARQUET", "json": "JSON", "jsonl": "JSONL", "ndjson": "JSONL", "geojson": "GEOJSON",
    "xml": "XML", "gml": "GML", "shp": "SHP", "gpkg": "GPKG", "px": "PX", "ttl": "RDF_TURTLE",
    "turtle": "RDF_TURTLE", "n3": "N3", "rdf": "RDF_XML", "rdfxml": "RDF_XML", "owl": "RDF_XML",
    "jsonld": "JSON_LD", "nt": "NT", "zip": "ZIP", "html": "HTML", "htm": "HTML", "pdf": "PDF",
    "kml": "KML", "kmz": "KML", "gpx": "GPX", "tif": "TIFF", "tiff": "TIFF", "jpg": "JPEG",
    "jpeg": "JPEG", "png": "PNG", "txt": "TXT", "dxf": "DXF", "fgb": "FGB", "interlis": "INTERLIS",
    "xtf": "INTERLIS", "itf": "INTERLIS", "nc": "NETCDF",
}

FAMILIES = {
    "tabular": {"CSV", "TSV", "XLSX", "XLS", "ODS", "PARQUET", "JSONL"},
    "geo": {"SHP", "GPKG", "GML", "WFS"},
    "px": {"PX", "PXWEB"},
    "tree": {"JSON", "XML"},
    "rdf": {"RDF_TURTLE", "N3", "RDF_XML", "JSON_LD", "NT"},
}
IN_SCOPE = set().union(*FAMILIES.values())
# Declared types worth a look although they have no engine of their own:
# containers, untyped files and APIs often hold an in-scope format.
SNIFF_WORTHY = {"ZIP", "TXT", "OCTET", "REST"}
OUT_OF_SCOPE = {"HTML", "PDF", "WMS", "WMTS", "TIFF", "JPEG", "PNG", "KML", "GPX", "GEOJSON",
                "DXF", "SPARQL", "GDB", "FEATHER", "FGB", "NETCDF", "OV2", "INTERLIS"}

RDF_TOKENS = FAMILIES["rdf"]


def family(token: str | None) -> str | None:
    for name, tokens in FAMILIES.items():
        if token in tokens:
            return name
    return None


def eu_iri(token: str | None) -> str | None:
    code = TO_EU.get(token or "")
    return EU_FILE_TYPE + code if code else None


def from_format(value: str) -> str | None:
    """dct:format: an EU file-type IRI (as IRI or literal) or free text."""
    v = value.strip()
    if v.startswith(EU_FILE_TYPE):
        code = v[len(EU_FILE_TYPE):].upper()
        return EU_ALIASES[code] if code in EU_ALIASES else code
    if v.startswith("http"):  # e.g. a Wikipedia link instead of a format
        return None
    return FREE_TEXT.get(v.upper()) or MEDIA_TYPES.get(v.lower())


def from_media_type(value: str) -> str | None:
    """dcat:mediaType: a literal or an IANA IRI (http or https style)."""
    v = re.sub(r"^https?://www\.iana\.org/assignments/media-types/", "", value.strip()).lower()
    return MEDIA_TYPES.get(v.split(";")[0].strip())


def from_url(url: str) -> str | None:
    """The type a URL suggests: extension, Opendatasoft export, service parameter."""
    if not url:
        return None
    u = urlparse(url)
    query = {k.lower(): [x.lower() for x in v] for k, v in parse_qs(u.query).items()}
    if "wfs" in query.get("service", []) or "wfs" in u.netloc.split(".")[0] \
            or re.search(r"/wfs(server)?/?$", u.path, re.I):
        return "WFS"
    if m := re.search(r"/exports/([a-z0-9]+)/?$", u.path):
        return EXTENSIONS.get(m.group(1)) or FREE_TEXT.get(m.group(1).upper())
    path = unquote(u.path).lower()
    # Double extensions: name.shp.zip, NAME-SHP.zip, name.gpkg.zip
    if m := re.search(r"[.\-_](shp|gpkg|gml|csv|xlsx|json|geojson|xml|xtf|itf|dxf|kml|gdb)\.zip$", path):
        return EXTENSIONS.get(m.group(1)) or FREE_TEXT[m.group(1).upper()]
    if pxweb_api(url):
        return "PX"
    m = re.search(r"\.([a-z0-9]{2,7})$", path)
    return EXTENSIONS.get(m.group(1)) if m else None


def declared_types(formats: list[str], media_types: list[str], urls: list[str]) -> list[str]:
    """All types the metadata suggests, most trusted first; conflicts are kept."""
    out = []
    for t in ([from_format(f) for f in formats] + [from_media_type(m) for m in media_types]
              + [from_url(u) for u in urls]):
        if t and t not in out:
            out.append(t)
    # A ZIP or TXT next to a more specific type adds nothing (CSV in ZIP, SHP as zip).
    if len(out) > 1:
        out = [t for t in out if t not in {"ZIP", "TXT", "OCTET"}] or out
    return out


def worth_fetching(declared: list[str]) -> bool:
    """Skip without a request only when every declared type is known and out of scope."""
    return not declared or any(t not in OUT_OF_SCOPE for t in declared)


def pxweb_api(url: str) -> str | None:
    """PxWeb UI or BFS asset link → the table's API v1 URL, or None."""
    u = urlparse(url)
    path = unquote(u.path)
    if m := re.match(r"^/asset/([a-z]{2})/(px-x-[\w-]+)/?$", path):        # bfs.admin.ch asset page
        lang, table = m.groups()
        return f"https://www.pxweb.bfs.admin.ch/api/v1/{lang}/{table}/{table}.px"
    if "/api/v1/" in path.lower() and path.lower().endswith(".px"):
        return url
    m = re.match(r"^(.*?)/pxweb/([a-z]{2})/([^/]+)/(?:([^/]+)/)?([^/]+\.px)/?$", path, re.I)
    if not m:
        return None
    prefix, lang, db, folder, table = m.groups()
    parts = folder.split("__")[1:] if folder and "__" in folder else []
    segments = [prefix + "/api/v1", lang, db, *parts, table]
    return urlunparse((u.scheme, u.netloc, quote("/".join(segments)), "", "", ""))
