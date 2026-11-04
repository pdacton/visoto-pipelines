"""Tabular engine: CSV, XLSX, XLS, ODS, Parquet and tabular JSON.

DuckDB reads the sample and computes per-field statistics (SUMMARIZE, code
lists); Frictionless types text formats, and DuckDB's sniffer wins where it
recognises dates Frictionless leaves as strings (dd.mm.yyyy).
"""
import csv
import datetime
import decimal
import json
import math
import re
from pathlib import Path

import duckdb
from frictionless import Detector, describe

from ..model import (CATEGORICAL_MAX, Field, Part, TEMPORAL, truncate_examples, unique_slugs)
from . import EngineError, NotTabular

MISSING = ["", "...", "..", "-", "NA", "N/A", "n/a", "null", "NULL", "x", "X", "*"]
BOOLEAN_WORDS = {"ja", "nein", "oui", "non", "si", "sì", "no", "yes", "true", "false", "0", "1",
                 "j", "n", "y", "wahr", "falsch", "vrai", "faux", "vero", "falso"}
DUCKDB_TYPES = [  # (prefix of the DuckDB type, Table Schema type)
    ("TIMESTAMP", "datetime"), ("DATE", "date"), ("TIME", "time"), ("INTERVAL", "duration"),
    ("BOOLEAN", "boolean"), ("DECIMAL", "number"), ("DOUBLE", "number"), ("FLOAT", "number"),
    ("REAL", "number"), ("HUGEINT", "integer"), ("UHUGEINT", "integer"), ("BIGINT", "integer"),
    ("UBIGINT", "integer"), ("INTEGER", "integer"), ("UINTEGER", "integer"), ("SMALLINT", "integer"),
    ("USMALLINT", "integer"), ("TINYINT", "integer"), ("UTINYINT", "integer"), ("VARCHAR", "string"),
    ("UUID", "string"), ("BLOB", "any"), ("GEOMETRY", "geojson"), ("STRUCT", "object"), ("MAP", "object"),
    ("JSON", "object"),
]
NUMERIC_STATS = {"number", "integer"}
# INTERLIS / GeoPackage bookkeeping tables that describe no data
SYSTEM_TABLES = re.compile(r"^(T_ILI2DB_|T_KEY_OBJECT$|gpkg_|rtree_|sqlite_)", re.I)


def connect(tmp: Path) -> duckdb.DuckDBPyConnection:
    tmp.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(config={"memory_limit": "512MB", "threads": 2, "temp_directory": str(tmp)})


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def lit(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def table_schema_type(duck_type: str) -> str:
    t = duck_type.upper()
    if t.endswith("[]") or t.startswith("LIST"):
        return "array"
    for prefix, ts in DUCKDB_TYPES:
        if t.startswith(prefix):
            return ts
    return "any"


def plain(v):
    """A JSON-friendly scalar."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, int):
        return v
    if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
        return v.isoformat()
    return str(v)


def number(v):
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else (int(f) if f.is_integer() and abs(f) < 2**53 else f)
    except (TypeError, ValueError):
        return None


# --- statistics shared by the tabular and geo engines ---------------------------------

def profile_relation(con, source: str, sample_rows: int, skip: set[str] = frozenset()) -> tuple[list[Field], int]:
    """Fields with statistics for `SELECT * FROM <source> LIMIT sample_rows`."""
    con.execute(f"CREATE OR REPLACE TEMP TABLE sample AS SELECT * FROM {source} LIMIT {sample_rows}")
    rows = con.sql("SELECT COUNT(*) FROM sample").fetchall()[0][0]
    described = con.sql("DESCRIBE sample").fetchall()
    summary = {}
    simple = [c for c, t, *_ in described
              if c not in skip and table_schema_type(t) not in ("object", "array", "geojson", "any")]
    if simple and rows:
        cols = ", ".join(q(c) for c in simple)
        for r in con.sql(f"SUMMARIZE SELECT {cols} FROM sample").fetchall():
            summary[r[0]] = r
    fields = []
    for name, duck_type, *_ in described:
        if name in skip:
            continue
        ts = table_schema_type(duck_type)
        f = Field(name=name, type=ts, stats={"duckdbType": duck_type})
        s = summary.get(name)
        if s:
            _, _, mn, mx, approx, avg, std, q25, q50, q75, count, nullpct = s
            numeric = ts in NUMERIC_STATS
            conv = number if numeric else plain
            f.stats.update({
                "count": count, "nullPercentage": float(nullpct or 0), "distinct": approx,
                "min": conv(mn), "max": conv(mx),
                "mean": number(avg) if numeric else None, "std": number(std) if numeric else None,
                "q25": conv(q25) if numeric or ts in TEMPORAL else None,
                "q50": conv(q50) if numeric or ts in TEMPORAL else None,
                "q75": conv(q75) if numeric or ts in TEMPORAL else None,
            })
            nonnull = round(count * (1 - float(nullpct or 0) / 100))
            if approx is not None and approx <= CATEGORICAL_MAX * 1.2:
                values = [plain(v[0]) for v in con.sql(
                    f"SELECT DISTINCT {q(name)} FROM sample WHERE {q(name)} IS NOT NULL ORDER BY 1 "
                    f"LIMIT {CATEGORICAL_MAX + 1}").fetchall()]
                if len(values) <= CATEGORICAL_MAX:
                    f.stats["distinct"] = len(values)
                    f.stats["values"] = values
                    if nonnull and len(values) <= 0.2 * nonnull and ts not in ("number",):
                        f.categorical = True
                    if len(values) == 2 and {str(v).lower() for v in values} <= BOOLEAN_WORDS \
                            and ts != "boolean":
                        f.booleanCandidate = True
        else:
            nulls = con.sql(f"SELECT COUNT(*) FILTER (WHERE {q(name)} IS NULL) FROM sample").fetchall()[0][0]
            f.stats.update({"count": rows, "nullPercentage": round(100 * nulls / rows, 2) if rows else 0})
        f.stats = {k: v for k, v in f.stats.items() if v is not None}
        if ts != "geojson":
            ex = con.sql(f"SELECT DISTINCT {q(name)}::VARCHAR FROM (SELECT {q(name)} FROM sample "
                         f"WHERE {q(name)} IS NOT NULL LIMIT 200) LIMIT 3").fetchall()
            f.examples = truncate_examples(v[0] for v in ex)
        fields.append(f)
    return fields, rows


def integral_numbers(con, fields: list[Field]) -> None:
    """JSON has one number type; DuckDB reads a column as DOUBLE once a value is null or large."""
    for f in fields:
        if f.type == "number" and f.stats.get("duckdbType") == "DOUBLE":
            whole = con.sql(f"SELECT bool_and({q(f.name)} = floor({q(f.name)})) FROM sample").fetchall()[0][0]
            if whole:
                f.type = "integer"
                f.examples = [e[:-2] if e.endswith(".0") else e for e in f.examples]


def keys_unique(con, part: Part) -> bool | None:
    """Do the key dimensions identify every sample row? None when there is nothing to check."""
    keys = part.key_fields()
    if not keys or len(keys) == len(part.fields):
        return None
    cols = ", ".join(q(f.name) for f in keys)
    total, distinct = con.sql(
        f"SELECT (SELECT COUNT(*) FROM sample), (SELECT COUNT(*) FROM (SELECT DISTINCT {cols} FROM sample))"
    ).fetchall()[0]
    return bool(total) and total == distinct


# --- readers ------------------------------------------------------------------------

def to_utf8(path: Path, enc: str, tmp: Path) -> Path:
    if enc in ("utf-8", "utf-8-sig", "ascii"):
        return path
    out = tmp / (path.stem + ".utf8.csv")
    out.write_text(path.read_bytes().decode(enc, errors="replace"), encoding="utf-8")
    return out


def csv_source(con, path: Path, dialect: dict) -> tuple[str, dict]:
    """DuckDB's read_csv over the sample, with the sniffed dialect."""
    nulls = ", ".join(lit(m) for m in MISSING)
    try:
        sn = con.sql(f"SELECT Delimiter, HasHeader, SkipRows, DateFormat, TimestampFormat "
                     f"FROM sniff_csv({lit(path)}, sample_size=-1, strict_mode=false)").fetchall()[0]
        delim, header, skip, datefmt, tsfmt = sn
    except duckdb.Error:
        delim, header, skip, datefmt, tsfmt = dialect.get("delimiter", ","), True, 0, None, None
    opts = [f"delim={lit(delim)}", f"header={str(bool(header)).lower()}", f"skip={int(skip or 0)}",
            f"nullstr=[{nulls}]", "sample_size=-1", "strict_mode=false", "null_padding=true",
            "ignore_errors=true"]
    if datefmt:
        opts.append(f"dateformat={lit(datefmt)}")
    if tsfmt:
        opts.append(f"timestampformat={lit(tsfmt)}")
    found = {"delimiter": delim, "header": bool(header)}
    if skip:
        found["skipRows"] = int(skip)
    if datefmt:
        found["dateFormat"] = datefmt
    return f"read_csv({lit(path)}, {', '.join(opts)})", found


def frictionless_types(path: Path, delimiter: str, skip: int) -> list[dict]:
    """Frictionless field types, in column order; [] if it can't describe the file."""
    try:
        res = describe(str(path), type="resource", detector=Detector(
            sample_size=1000, field_confidence=0.9, field_missing_values=MISSING))
        return res.to_dict().get("schema", {}).get("fields", [])
    except Exception:  # noqa: BLE001 - Frictionless is a second opinion only
        return []


def reconcile(fields: list[Field], fl_fields: list[dict]) -> None:
    """Frictionless types for text sources; DuckDB's dates win over a Frictionless string."""
    if len(fl_fields) != len(fields):
        return
    for f, fl in zip(fields, fl_fields):
        duck = f.type
        ft = fl.get("type", "any")
        if ft == "string" and duck in ("date", "datetime", "time"):
            continue
        if ft in ("integer", "number") and duck == "string":
            continue        # DuckDB saw values Frictionless's sample didn't; keep string
        if ft in ("any", "object", "array", "geojson", "geopoint"):
            continue
        if ft == "number" and duck == "integer":
            continue
        f.type = ft
        if fl.get("format") and fl["format"] != "default":
            f.format = fl["format"]


# --- spreadsheets ---------------------------------------------------------------------

def sheets(path: Path, kind: str, max_rows: int):
    """(sheet name, rows) for every sheet, rows as lists of Python values."""
    if kind == "XLSX":
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            yield ws.title, [list(r) for r in ws.iter_rows(values_only=True, max_row=max_rows)]
        wb.close()
    elif kind == "XLS":
        import xlrd
        wb = xlrd.open_workbook(str(path), on_demand=True)
        for ws in wb.sheets():
            rows = []
            for i in range(min(ws.nrows, max_rows)):
                row = []
                for cell in ws.row(i):
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            row.append(xlrd.xldate.xldate_as_datetime(cell.value, wb.datemode))
                        except (ValueError, OverflowError):
                            row.append(cell.value)
                    elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        row.append(None)
                    else:
                        row.append(cell.value)
                rows.append(row)
            yield ws.name, rows
    elif kind == "ODS":
        import ezodf
        doc = ezodf.opendoc(str(path))
        for ws in doc.sheets:
            rows = []
            for i, r in enumerate(ws.rows()):
                if i >= max_rows:
                    break
                rows.append([c.value for c in r])
            yield ws.name, rows


def _filled(row) -> int:
    return sum(1 for v in row if v not in (None, ""))


def _texty(row) -> bool:
    vals = [v for v in row if v not in (None, "")]
    return bool(vals) and sum(isinstance(v, str) for v in vals) >= 0.8 * len(vals)


def find_header(rows: list[list]) -> tuple[int, int]:
    """(skipRows, headerRowCount): skip title rows, allow a two-line merged header."""
    width = max((_filled(r) for r in rows[:50]), default=0)
    if width < 2:
        return 0, 1
    for i, row in enumerate(rows[:30]):
        if _filled(row) >= max(2, 0.6 * width) and _texty(row):
            nxt = rows[i + 1] if i + 1 < len(rows) else []
            after = rows[i + 2] if i + 2 < len(rows) else []
            # A grouped first line (merged cells left empty) over a second text line
            if _filled(row) < width and _texty(nxt) and _filled(nxt) >= 0.6 * width and after and not _texty(after):
                return i, 2
            return i, 1
    return 0, 1


def sheet_to_csv(rows: list[list], out: Path) -> dict | None:
    """Write a sheet as a clean CSV; None if it holds no table."""
    rows = [list(r) for r in rows]
    while rows and _filled(rows[-1]) == 0:
        rows.pop()
    if len(rows) < 2:
        return None
    skip, nheader = find_header(rows)
    header_rows = rows[skip:skip + nheader]
    width = max(len(r) for r in rows[skip:])
    names = []
    carried = [None] * width
    for c in range(width):
        parts = []
        for h, hr in enumerate(header_rows):
            v = hr[c] if c < len(hr) else None
            if h == 0 and nheader > 1:          # forward-fill merged group labels
                v = v if v not in (None, "") else (carried[c - 1] if c else None)
                carried[c] = v
            if v not in (None, ""):
                parts.append(str(v).strip())
        names.append(" / ".join(dict.fromkeys(parts)) or f"column_{c + 1}")
    data = []
    for r in rows[skip + nheader:]:
        if _filled(r) == 0:
            break                               # notes and footnotes follow a blank row
        data.append([_cell(v) for v in (r + [None] * width)[:width]])
    # drop trailing all-empty columns
    used = [c for c in range(width) if any(row[c] != "" for row in data) or not names[c].startswith("column_")]
    if not data or len(used) < 1:
        return None
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([names[c] for c in used])
        w.writerows([[row[c] for c in used] for row in data])
    return {"skipRows": skip, "headerRowCount": nheader}


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime.datetime):
        return v.date().isoformat() if v.time() == datetime.time() else v.isoformat()
    if isinstance(v, (datetime.date, datetime.time)):
        return v.isoformat()
    return str(v).strip()


# --- JSON -----------------------------------------------------------------------------

def json_records(path: Path, tmp: Path) -> tuple[Path, str | None]:
    """Records from the root array, or from a single top-level array property → JSONL."""
    try:
        data = json.loads(path.read_bytes())
    except ValueError as e:
        raise EngineError(f"json-parse:{e}"[:120])
    key = None
    if isinstance(data, dict):
        arrays = [k for k, v in data.items() if isinstance(v, list)]
        if len(arrays) != 1 or any(isinstance(v, dict) for k, v in data.items() if k != arrays[0]):
            raise NotTabular("json-not-records")
        key = arrays[0]
        data = data[key]
    if not isinstance(data, list) or not data or not all(isinstance(r, dict) for r in data[:100]):
        raise NotTabular("json-not-records")
    # Records nested beyond one level are a tree, not a table.
    if any(isinstance(v, dict) and any(isinstance(x, (dict, list)) for x in v.values())
           for r in data[:100] for v in r.values()):
        raise NotTabular("json-nested-records")
    out = tmp / (path.stem + ".records.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for r in data:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out, key


# --- entry point ----------------------------------------------------------------------

def profile(path: Path, kind: str, cfg, tmp: Path, detail: dict) -> list[Part]:
    """Parts for a tabular sample; kind is the sniffed token (CSV, XLSX, PARQUET, JSON, ...)."""
    rows = cfg.int("SAMPLE_ROWS")
    con = connect(tmp / "duckdb")
    try:
        if kind in ("CSV", "TSV", "TXT"):
            return [csv_part(con, path, detail, rows, tmp, "main", None)]
        if kind in ("XLSX", "XLS", "ODS"):
            parts = []
            names = []
            for name, sheet_rows in sheets(path, kind, rows + 60):
                out = tmp / f"sheet-{len(names)}.csv"
                found = sheet_to_csv(sheet_rows, out)
                if found is None:
                    continue
                names.append(name)
                part = csv_part(con, out, {"delimiter": ",", "encoding": "utf-8"}, rows, tmp, name, name)
                part.dialect = {**found, "header": True}
                parts.append(part)
            for part, s in zip(parts, unique_slugs(names)):
                part.slug = s if len(parts) > 1 else "main"
            if not parts:
                raise EngineError("no-table-in-workbook")
            return parts
        if kind == "PARQUET":
            return [parquet_part(con, path, detail, rows)]
        if kind in ("JSON", "JSONL"):
            src, key = (path, None) if kind == "JSONL" else json_records(path, tmp)
            source = f"read_json({lit(src)}, format='newline_delimited', sample_size=-1, maximum_depth=2)"
            fields, n = profile_relation(con, source, rows)
            integral_numbers(con, fields)
            part = Part(label=key, rowCount=n, fields=fields)
            if key:
                part.dialect = {"recordsPath": f"/{key}"}
            part.keysUnique = keys_unique(con, part)
            return [part]
        raise EngineError(f"tabular-unsupported:{kind}")
    finally:
        con.close()


def csv_part(con, path: Path, detail: dict, rows: int, tmp: Path, slug: str, label: str | None) -> Part:
    enc = detail.get("encoding", "utf-8")
    src_path = to_utf8(path, enc, tmp)
    source, dialect = csv_source(con, src_path, detail)
    try:
        fields, n = profile_relation(con, source, rows)
    except duckdb.Error as e:
        raise EngineError(f"duckdb:{str(e).splitlines()[0]}"[:200])
    reconcile(fields, frictionless_types(src_path, dialect["delimiter"], dialect.get("skipRows", 0)))
    for f in fields:
        if f.type in ("date", "datetime") and dialect.get("dateFormat") and not f.format:
            f.format = dialect["dateFormat"]
    dialect["encoding"] = {"utf-8-sig": "utf-8"}.get(enc, enc)
    part = Part(slug=slug, label=label, rowCount=n, dialect=dialect, fields=fields)
    part.keysUnique = keys_unique(con, part)
    return part


def parquet_part(con, path: Path, detail: dict, rows: int) -> Part:
    p = lit(path)
    total = con.sql(f"SELECT SUM(num_rows) FROM parquet_file_metadata({p})").fetchall()[0][0]
    if detail.get("footerOnly"):
        # Only the footer was downloaded: types from the schema, min/max/nulls from row-group stats.
        fields = []
        for name, duck_type in con.sql(f"SELECT name, type FROM parquet_schema({p}) WHERE num_children IS NULL "
                                       f"OR num_children = 0").fetchall():
            fields.append(Field(name=name, type=_parquet_type(duck_type)))
        stats = {r[0]: r[1:] for r in con.sql(
            f"SELECT path_in_schema, MIN(stats_min_value), MAX(stats_max_value), SUM(stats_null_count) "
            f"FROM parquet_metadata({p}) GROUP BY 1").fetchall()}
        for f in fields:
            if s := stats.get(f.name):
                conv = number if f.type in NUMERIC_STATS else plain
                f.stats = {k: v for k, v in {"count": total, "min": conv(s[0]), "max": conv(s[1]),
                           "nullPercentage": round(100 * (s[2] or 0) / total, 2) if total else None}.items()
                           if v is not None}
        return Part(rowCount=total, fields=fields)
    fields, n = profile_relation(con, f"read_parquet({p})", rows)
    part = Part(rowCount=total or n, fields=fields)
    part.keysUnique = keys_unique(con, part)
    return part


def _parquet_type(physical: str) -> str:
    return {"INT32": "integer", "INT64": "integer", "FLOAT": "number", "DOUBLE": "number",
            "BOOLEAN": "boolean", "BYTE_ARRAY": "string", "FIXED_LEN_BYTE_ARRAY": "string"}.get(physical, "any")
