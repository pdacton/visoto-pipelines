"""Code-list matching: every fingerprint's value sample against every list, version and level.

containment: share of the slot's distinct values found in one level of a scheme.
coverage:    share of that level's codes seen in the slot (low is normal for samples and subsets).

A slot is linked automatically only when the best list is unambiguous: high containment, enough
distinct values and a clear lead over every other list. Otherwise the top lists stay candidates,
decided later (by a person or the concept step, which sees the column's name and context).
A slot links to a version when its values tell the versions apart, otherwise to the list.

Dense integer ranges (a level of at least 50 integer codes covering 95% of min..max, e.g. age in
hours 0–1200) contain almost any integer column; a hit there says nothing, so it is never linked
automatically and ranks after the other lists. The same holds locally: when integer values lie in
a stretch where nearly every integer is a code of the level (density at least RANGE_DENSITY), a
sequence of record numbers fits as well as real codes, so the hit is not linked automatically
("range-overlap").
"""
import bisect
import re
from dataclasses import dataclass, field

import duckdb

from . import bulk
from .lindas import norm

EPS = 1e-9
RANGE_DENSITY = 0.8


@dataclass
class Thresholds:
    min_containment: float = 0.95
    min_distinct: int = 5
    min_lead: float = 0.1
    candidate_min: float = 0.5
    candidates: int = 3

    @classmethod
    def from_config(cls, cfg) -> "Thresholds":
        return cls(cfg.float("CODE_MIN_CONTAINMENT"), cfg.int("CODE_MIN_DISTINCT"), cfg.float("CODE_MIN_LEAD"),
                   cfg.float("CODE_CANDIDATE_MIN"), cfg.int("CANDIDATES"))


@dataclass
class Hit:
    list: str                 # LINDAS list (identity scheme)
    scheme: str               # the scheme linked: the list, or one version of it
    version: str | None
    level: str | None
    containment: float
    coverage: float
    distinct: int             # the slot's distinct values (normalised)
    dense: bool = False       # the level is a dense integer range


@dataclass
class CodeResult:
    candidates: list[Hit] = field(default_factory=list)   # best per list, ranked
    automatic: Hit | None = None
    reason: str = ""                                       # why nothing or only candidates


def matchable(slot: dict) -> bool:
    """Slots worth comparing with code lists: values present, not geometry, not nested."""
    return bool(slot.get("sample")) and not slot.get("nested") and \
        slot.get("datatype") != "http://www.opengis.net/ont/geosparql#wktLiteral" and \
        slot.get("type") not in ("number", "boolean", "date", "datetime", "time", "duration")


def scores(con, samples: dict[str, list[str]]) -> dict[str, list[tuple]]:
    """fingerprint → rows (list, scheme, version, level, containment, coverage, distinct, dense) above zero."""
    rows = [(fp, v) for fp, values in samples.items() for v in {norm(x) for x in values} - {None}]
    if not rows:
        return {}
    con.execute("CREATE OR REPLACE TEMP TABLE sv (fp VARCHAR, v VARCHAR)")
    bulk.insert(con, "sv", ["fp", "v"], rows)
    result = con.execute("""
        WITH n AS (SELECT fp, COUNT(*) AS k FROM sv GROUP BY fp),
        lvl AS (SELECT scheme, COALESCE(level, '') AS level, COUNT(DISTINCT norm) AS size,
                       COUNT(DISTINCT norm) FILTER (WHERE regexp_full_match(norm, '-?[0-9]+')) AS ints,
                       MIN(TRY_CAST(norm AS BIGINT)) AS lo, MAX(TRY_CAST(norm AS BIGINT)) AS hi
                FROM codes GROUP BY ALL),
        hits AS (SELECT sv.fp, c.list, c.scheme, c.version, COALESCE(c.level, '') AS level, COUNT(DISTINCT sv.v) AS h
                 FROM sv JOIN codes c ON c.norm = sv.v GROUP BY ALL)
        SELECT hits.fp, hits.list, hits.scheme, hits.version, hits.level,
               hits.h / n.k AS containment, hits.h / lvl.size AS coverage, n.k,
               (lvl.size = lvl.ints AND lvl.size >= 50 AND lvl.size >= 0.95 * (lvl.hi - lvl.lo + 1)) AS dense
        FROM hits JOIN n USING (fp) JOIN lvl USING (scheme, level)""").fetchall()
    out: dict[str, list[tuple]] = {}
    for fp, *rest in result:
        out.setdefault(fp, []).append(tuple(rest))
    return out


def versions_per_list(con) -> dict[str, int]:
    return dict(con.execute("SELECT list, COUNT(*) FROM schemes WHERE version IS NOT NULL GROUP BY list").fetchall())


def int_range(sample: list[str]) -> tuple[int, int] | None:
    """(min, max) when every value is an integer, else None."""
    vals = [norm(v) for v in sample]
    if not vals or not all(v and re.fullmatch(r"-?\d+", v) for v in vals):
        return None
    nums = [int(v) for v in vals]
    return min(nums), max(nums)


class Density:
    """Share of the integers in [lo, hi] that are codes of a scheme level (cached per level)."""

    def __init__(self, con):
        self.con, self.cache = con, {}

    def __call__(self, scheme: str, level: str | None, lo: int, hi: int) -> float:
        key = (scheme, level or "")
        if key not in self.cache:
            rows = self.con.execute("SELECT DISTINCT TRY_CAST(norm AS BIGINT) AS n FROM codes WHERE scheme = ? "
                                    "AND COALESCE(level, '') = ? AND n IS NOT NULL ORDER BY n", list(key)).fetchall()
            self.cache[key] = [r[0] for r in rows]
        codes = self.cache[key]
        inside = bisect.bisect_right(codes, hi) - bisect.bisect_left(codes, lo)
        return inside / (hi - lo + 1)


def decide(rows: list[tuple], versions: dict[str, int], t: Thresholds, span: tuple[int, int] | None = None,
           density=None) -> CodeResult:
    """Rank the lists for one fingerprint and decide whether one is linked automatically."""
    best_list: dict[str, tuple] = {}          # list → best identity row (containment, coverage, level)
    by_version: dict[tuple, list[tuple]] = {}
    for lst, scheme, version, level, c, cov, k, dense in rows:
        row = (lst, scheme, version, level, c, cov, k, bool(dense))
        if version is None:
            cur = best_list.get(lst)
            if cur is None or (not dense, c, cov) > (not cur[7], cur[4], cur[5]):
                best_list[lst] = row
        else:
            by_version.setdefault((lst, level), []).append(row)
    # Lists without identity codes: their versions stand in
    for (lst, level), vrows in by_version.items():
        if lst not in best_list:
            best_list[lst] = max(vrows, key=lambda r: (not r[7], r[4], r[5]))
    ranked = sorted(best_list.values(), key=lambda r: (r[7], -r[4], -r[5], r[0]))
    hits = []
    for lst, scheme, version, level, c, cov, k, dense in ranked:
        if c + EPS < t.candidate_min:
            continue
        # most specific entry the values support: a single version as good as the list
        tied = [r for r in by_version.get((lst, level), []) if r[4] + EPS >= c]
        if len(tied) == 1 and versions.get(lst, 0) > 1:
            _, scheme, version, _, c, cov, _, _ = tied[0]
        elif version is not None and len(tied) != 1:
            scheme, version = lst, None
        hits.append(Hit(lst, scheme, version, level or None, round(c, 4), round(cov, 4), k, dense))
    res = CodeResult(candidates=hits[:t.candidates])
    if not hits:
        res.reason = "no-list"
        return res
    best = hits[0]
    rivals = [h for h in hits[1:] if not h.dense]
    lead = best.containment - (rivals[0].containment if rivals else 0.0)
    if best.dense:
        res.reason = "dense-range"
    elif span and density and span[1] > span[0] and density(best.scheme, best.level, *span) + EPS >= RANGE_DENSITY:
        res.reason = "range-overlap"
    elif best.containment + EPS < t.min_containment:
        res.reason = "low-containment"
    elif best.distinct < t.min_distinct:
        res.reason = "few-values"
    elif lead + EPS < t.min_lead:
        res.reason = "ambiguous"
    else:
        res.automatic = best
    return res


def match_all(codes_db, samples: dict[str, list[str]], t: Thresholds) -> dict[str, CodeResult]:
    con = duckdb.connect(str(codes_db), read_only=True)
    try:
        versions = versions_per_list(con)
        rows = scores(con, samples)
        density = Density(con)
        return {fp: decide(rows.get(fp, []), versions, t, int_range(samples[fp]), density) for fp in samples}
    finally:
        con.close()
