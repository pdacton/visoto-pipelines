"""Infer structure of a tabular distribution with DuckDB + Frictionless.

Usage: python infer_tabular.py <path-or-url> [--format csv|xlsx|parquet]
Output: Frictionless Table Schema (JSON) enriched with DuckDB statistics.
"""
import json
import sys

import duckdb
from frictionless import Detector, describe

SAMPLE_ROWS = 10_000
MISSING = ["", "...", "..", "-", "NA", "n/a", "null"]
DUCKDB_TO_TABLE_SCHEMA = {"DATE": "date", "TIMESTAMP": "datetime", "TIMESTAMP WITH TIME ZONE": "datetime",
                          "TIME": "time", "BIGINT": "integer", "INTEGER": "integer", "DOUBLE": "number",
                          "BOOLEAN": "boolean", "VARCHAR": "string"}
BOOLEAN_WORDS = {"ja", "nein", "oui", "non", "si", "sì", "no", "yes", "true", "false", "0", "1"}


def duckdb_profile(src: str, fmt: str):
    con = duckdb.connect(config={"memory_limit": "512MB", "threads": 2})
    if src.startswith("http"):
        con.sql("INSTALL httpfs; LOAD httpfs;")
    if fmt == "csv":
        sniff = con.sql(f"SELECT Delimiter, HasHeader, Columns, DateFormat FROM sniff_csv('{src}')").fetchall()[0]
        nulls = ", ".join(f"'{m}'" for m in MISSING)
        reader = f"read_csv('{src}', nullstr=[{nulls}], sample_size={SAMPLE_ROWS})"
        dialect = {"delimiter": sniff[0], "header": sniff[1], "dateFormat": sniff[3]}
    elif fmt == "xlsx":
        con.sql("INSTALL excel; LOAD excel;")
        reader, dialect = f"read_xlsx('{src}')", {}
    else:
        reader, dialect = f"read_parquet('{src}')", {}

    rel = con.sql(f"SELECT * FROM {reader} LIMIT {SAMPLE_ROWS}")
    stats = {
        r[0]: {
            "duckdbType": r[1], "min": r[2], "max": r[3], "approxUnique": r[4],
            "mean": r[5], "std": r[6], "q25": r[7], "q50": r[8], "q75": r[9],
            "count": r[10], "nullPercentage": float(r[11]),
        }
        for r in con.sql(f"SUMMARIZE {rel.sql_query()}").fetchall()
    }
    samples = {c: [str(v) for v in col if v is not None][:3]
               for c, col in zip(rel.columns, zip(*rel.limit(20).fetchall()))}
    # full value list for low-cardinality columns → code list candidates
    for c, s in stats.items():
        if s["approxUnique"] <= 50:
            q = f'SELECT DISTINCT "{c}" FROM ({rel.sql_query()}) WHERE "{c}" IS NOT NULL ORDER BY 1'
            s["values"] = [str(r[0]) for r in con.sql(q).fetchall()]
    return dialect, stats, samples


def frictionless_schema(src: str):
    res = describe(src, type="resource",
                   detector=Detector(sample_size=1000, field_confidence=0.9, field_missing_values=MISSING))
    return res.to_dict()


def infer(src: str, fmt: str = "csv") -> dict:
    dialect, stats, samples = duckdb_profile(src, fmt)
    resource = frictionless_schema(src)
    for field in resource["schema"]["fields"]:
        s = stats.get(field["name"], {})
        field["stats"] = {k: v for k, v in s.items() if v is not None}
        field["examples"] = samples.get(field["name"], [])
        # DuckDB's sniffer knows locale date formats (dd.mm.yyyy) that Frictionless leaves as string
        dd_type = DUCKDB_TO_TABLE_SCHEMA.get(s.get("duckdbType", ""))
        if field["type"] == "string" and dd_type in ("date", "datetime", "time"):
            field["type"] = dd_type
            field["format"] = dialect.get("dateFormat") or "any"
        # categorical hint: few distinct values relative to rows
        if s and s["count"] and s["approxUnique"] <= 50 and s["approxUnique"] <= 0.2 * s["count"]:
            field["categorical"] = True
            if {v.lower() for v in field["examples"]} <= BOOLEAN_WORDS and s["approxUnique"] == 2:
                field["x-booleanCandidate"] = True
    resource["x-duckdbDialect"] = dialect
    return resource


if __name__ == "__main__":
    src = sys.argv[1]
    fmt = sys.argv[sys.argv.index("--format") + 1] if "--format" in sys.argv else src.rsplit(".", 1)[-1].lower()
    print(json.dumps(infer(src, fmt), indent=2, ensure_ascii=False, default=str))
