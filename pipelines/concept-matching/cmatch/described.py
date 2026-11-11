"""Described value domains, made by rule from a slot's profile, without any lookup.

The identifier is built from the properties, so two slots with the same representation reach the
same entry: datatype + unit + format, or for geometries geometry type + coordinate reference system.
Examples: `date`, `date-dd.mm.yyyy`, `decimal-CCY_CHF`, `geo-MultiPolygon-EPSG2056`.
How finely the rules cut is an open question; this cut keeps ranges out of the identifier.
"""
import re

XSD = "http://www.w3.org/2001/XMLSchema#"
WKT = "http://www.opengis.net/ont/geosparql#wktLiteral"
QUDT_UNIT = "http://qudt.org/vocab/unit/"
STRFTIME = {"%d": "dd", "%m": "mm", "%Y": "yyyy", "%y": "yy", "%H": "hh", "%M": "mi", "%S": "ss", "%j": "ddd"}
TITLES = {  # datatype local name → English title
    "string": "Text", "integer": "Integer", "decimal": "Decimal number", "boolean": "Boolean",
    "date": "Date", "dateTime": "Date and time", "time": "Time", "gYear": "Year", "gYearMonth": "Year and month",
    "duration": "Duration", "anyURI": "URI",
}


def local(iri: str) -> str:
    return re.split(r"[#/]", iri.rstrip("/#"))[-1]


def format_slug(fmt: str | None, datatype_local: str) -> str | None:
    """A format as part of the identifier: strftime patterns spelled out, time units kept."""
    if not fmt or fmt in ("default", "any"):
        return None
    if datatype_local in ("date", "dateTime", "time", "gYear", "gYearMonth") and "%" in fmt:
        for k, v in STRFTIME.items():
            fmt = fmt.replace(k, v)
    s = re.sub(r"[^A-Za-z0-9.:_-]+", "_", fmt).strip("_")
    return s or None


def key(slot: dict) -> tuple[str, dict] | None:
    """(identifier, value-domain fields) of the slot's described value domain, or None (no datatype)."""
    dt = slot.get("datatype")
    if not dt or slot.get("nested"):
        return None
    container = slot.get("container") or {}
    if dt == WKT:
        gtype = container.get("geometryType") or "Geometry"
        crs = container.get("crs")
        ident = f"geo-{gtype.replace('|', '_')}" + (f"-EPSG{crs}" if crs else "")
        title = f"Geometry ({gtype}" + (f", EPSG:{crs}" if crs else "") + ")"
        return ident, {"datatype": WKT, "title": {"en": title}}
    dl = local(dt)
    unit = slot.get("unit") if (slot.get("unit") or "").startswith(QUDT_UNIT) else None
    fmt = format_slug(slot.get("format"), dl)
    parts = [dl] + ([local(unit)] if unit else []) + ([fmt] if fmt else [])
    ident = "-".join(parts)
    title = TITLES.get(dl, dl)
    extras = ([f"unit {local(unit)}"] if unit else []) + ([f"format {slot['format']}"] if fmt else [])
    if extras:
        title += f" ({', '.join(extras)})"
    fields = {"datatype": dt, "title": {"en": title}}
    if unit:
        fields["unit"] = unit
    return ident, fields
