"""Geo engine: SHP (in ZIP), GPKG, GML and WFS samples through DuckDB `spatial` (GDAL).

One part per layer, with geometry type, CRS, a geo:wktLiteral geometry field and
attribute statistics as in the tabular engine. pyogrio is the fallback when
ST_Read can't open a driver; it gives field types without statistics.
"""
import re
from pathlib import Path

import duckdb

from ..model import Field, Part, unique_slugs
from . import EngineError
from .tabular import SYSTEM_TABLES, connect, keys_unique, lit, profile_relation, q

GEO_WKT = "http://www.opengis.net/ont/geosparql#wktLiteral"
OGR_TYPES = {"Integer": "integer", "Integer64": "integer", "Real": "number", "String": "string",
             "Date": "date", "DateTime": "datetime", "Time": "time", "Binary": "any",
             "int32": "integer", "int64": "integer", "float64": "number", "float32": "number",
             "object": "string", "bool": "boolean", "datetime64[ms]": "datetime"}


def layers_of(path: str, token: str, detail: dict) -> list[tuple[str | None, str]]:
    """(label, file) to read; WFS samples are one GML file per layer."""
    if token == "WFS":
        return [(l["name"], str(Path(path) / l["file"]))
                for l in detail.get("layerFiles", []) if l.get("status") == "ok"]
    return [(None, path)]


def profile(path: Path, token: str, cfg, tmp: Path, detail: dict) -> list[Part]:
    rows = cfg.int("SAMPLE_ROWS")
    con = connect(tmp / "duckdb")
    con.execute("LOAD spatial")
    parts = []
    try:
        for label, file in layers_of(str(path), token, detail):
            try:
                meta = con.sql(f"SELECT layers FROM ST_Read_Meta({lit(file)})").fetchall()
            except duckdb.Error as e:
                parts += fallback(file, label, str(e))
                continue
            layers = meta[0][0] if meta else []
            for layer in layers:
                if SYSTEM_TABLES.match(layer["name"]):
                    continue
                parts.append(layer_part(con, file, layer, label or layer["name"], rows, single=len(layers) == 1))
    finally:
        con.close()
    if not parts:
        raise EngineError("no-layers")
    for part, s in zip(parts, unique_slugs([p.label or "main" for p in parts])):
        part.slug = s if len(parts) > 1 else "main"
    return parts


def layer_part(con, file: str, layer: dict, label: str, rows: int, single: bool) -> Part:
    source = f"ST_Read({lit(file)}, layer={lit(layer['name'])})" if not single else f"ST_Read({lit(file)})"
    geoms = layer.get("geometry_fields") or []
    try:
        try:
            fields, n = profile_relation(con, source, rows)
        except duckdb.Error as e:
            if "unicode" not in str(e).lower():
                raise
            # A shapefile in Latin-1 without a .cpg file: GDAL hands DuckDB invalid UTF-8.
            source = source[:-1] + ", open_options=['ENCODING=ISO-8859-1'])"
            fields, n = profile_relation(con, source, rows)
    except duckdb.Error:
        # Curves and other geometry types DuckDB can't convert: read the geometry as raw WKB.
        try:
            fields, n = profile_relation(con, source[:-1] + ", keep_wkb=true)", rows)
        except duckdb.Error as e:
            return fallback(file, label, str(e), layer=layer["name"])[0]
        names = {g["name"] for g in geoms} | {"geom", "wkb_geometry", "geometry"}
        for f in fields:
            if f.name in names and f.stats.get("duckdbType") == "BLOB":
                f.type = "geojson"
    geom_cols = [f for f in fields if f.type == "geojson"]
    for f in geom_cols:
        f.datatype = GEO_WKT
        f.stats = {k: v for k, v in f.stats.items() if k in ("count", "nullPercentage")}
    fields = [f for f in fields if f.name != "OGC_FID"]      # added by ST_Read for shapefiles
    part = Part(label=label, fields=fields)
    count = layer.get("feature_count")
    part.rowCount = count if count is not None and count >= 0 else n
    if geoms:
        crs = geoms[0].get("crs") or {}
        if crs.get("auth_name") == "EPSG" and crs.get("auth_code"):
            part.crs = str(crs["auth_code"])
        part.geometryType = geometry_name(geoms[0].get("type"))
    if geom_cols and not part.geometryType:
        try:
            types = con.sql(f"SELECT DISTINCT ST_GeometryType({q(geom_cols[0].name)})::VARCHAR FROM sample "
                            f"WHERE {q(geom_cols[0].name)} IS NOT NULL LIMIT 5").fetchall()
            names = sorted({geometry_name(t[0]) for t in types} - {None})
            part.geometryType = "|".join(names) or None
        except duckdb.Error:        # curves and other types DuckDB's WKB reader doesn't know
            pass
    if not part.crs:
        part.crs = srs_from_file(file)
    part.keysUnique = keys_unique(con, part)
    return part


OGC_NAMES = {n.upper(): n for n in (
    "Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection",
    "CircularString", "CompoundCurve", "CurvePolygon", "MultiCurve", "MultiSurface", "Curve", "Surface",
    "PolyhedralSurface", "Tin", "Triangle")}


def geometry_name(ogr: str | None) -> str | None:
    """OGR's "3D Multi Line String" or DuckDB's "MULTILINESTRING" → "MultiLineString"."""
    if not ogr or ogr.startswith(("Unknown", "Geometry", "None")):
        return None
    key = re.sub(r"^(3D|2D|Measured)\s+|\s+(Z|M|ZM)$|\s+", "", ogr.strip(), flags=re.I).upper()
    return OGC_NAMES.get(key, ogr)


def srs_from_file(file: str) -> str | None:
    """The EPSG code of a GML file's first srsName (GDAL doesn't report it for WFS output)."""
    if file.startswith("/vsi") or not file.lower().endswith((".gml", ".xml")):
        return None
    try:
        with open(file, "rb") as f:
            head = f.read(65536).decode("utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'srsName="[^"]*EPSG[:/]+(?:[\d.]*:)?(\d+)"', head)
    return m.group(1) if m else None


def fallback(file: str, label: str | None, error: str, layer: str | None = None) -> list[Part]:
    """Field types from pyogrio when DuckDB can't read the source."""
    import pyogrio
    try:
        infos = [(layer, pyogrio.read_info(file, layer=layer))] if layer else \
            [(name, pyogrio.read_info(file, layer=name)) for name, _ in pyogrio.list_layers(file)]
    except Exception as e:  # noqa: BLE001
        raise EngineError(f"geo-unreadable:{error.splitlines()[0][:80]}|{str(e)[:80]}")
    parts = []
    for name, info in infos:
        fields = [Field(name=n, type=OGR_TYPES.get(str(t)) or ("datetime" if str(t).startswith("datetime64")
                                                               else "any"))
                  for n, t in zip(info["fields"], info["dtypes"])]
        geom_column = info.get("geometry_name") or "geometry"
        if info.get("geometry_type"):
            fields.append(Field(name=geom_column, type="geojson", datatype=GEO_WKT))
        crs = info.get("crs") or ""
        parts.append(Part(label=label or name, rowCount=info.get("features"), fields=fields,
                          geometryType=geometry_name(info.get("geometry_type")),
                          crs=crs.split(":")[1] if crs.upper().startswith("EPSG:") else srs_from_file(file)))
    return parts

