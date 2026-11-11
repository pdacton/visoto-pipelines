"""Bulk inserts into DuckDB through a temporary CSV file (executemany is row by row and slow)."""
import csv
import os
import tempfile


def insert(con, table: str, columns: list[str], rows) -> int:
    fd, path = tempfile.mkstemp(suffix=".csv")
    n = 0
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, quoting=csv.QUOTE_ALL)
            for r in rows:
                w.writerow(["\\N" if v is None else v for v in r])
                n += 1
        if n:
            types = ", ".join(f"'{c}': 'VARCHAR'" for c in columns)
            con.execute(f"INSERT INTO {table} ({', '.join(columns)}) SELECT * FROM read_csv(?, header=false, "
                        f"quote='\"', escape='\"', nullstr='\\N', columns={{{types}}})", [path])
    finally:
        os.unlink(path)
    return n
