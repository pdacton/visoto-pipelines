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

Values are compared as notations and as labels (lindas.value_forms): a column of canton names and a
column of canton abbreviations reach the same list, and the hit records what matched (`matched`:
notation, label or both; `languages` of the labels). The same rules decide a label hit. Generic
labels ("Ja", "Nein", "Unbekannt", "Andere") say nothing on their own: they count towards
containment, but a list is linked automatically only when at least `min_distinct` of the matched
values are specific (notations or other labels; reason "generic-labels"). A label is generic
when it occurs in at least `generic_lists` lists and the levels it occurs in have at most
`generic_level_size` codes (median). Place names occur in as many lists ("Zürich" in 20), but in
large levels (median 56 codes); the few caught by the rule ("Ticino", also a region in small lists)
still count. A notation is stronger evidence than a label: at equal
containment a hit on notations ranks first, and a list hit only through its labels is no rival to
one hit on notations (canton abbreviations are the codes of the canton list and the labels of a
location-code list).
"""
import bisect
import re
from dataclasses import dataclass, field

import duckdb

from . import bulk
from .lindas import norm, value_forms

EPS = 1e-9
RANGE_DENSITY = 0.8


@dataclass
class Thresholds:
    min_containment: float = 0.95
    min_distinct: int = 5
    min_lead: float = 0.1
    candidate_min: float = 0.5
    candidates: int = 3
    generic_lists: int = 5
    generic_level_size: int = 20

    @classmethod
    def from_config(cls, cfg) -> "Thresholds":
        return cls(cfg.float("CODE_MIN_CONTAINMENT"), cfg.int("CODE_MIN_DISTINCT"), cfg.float("CODE_MIN_LEAD"),
                   cfg.float("CODE_CANDIDATE_MIN"), cfg.int("CANDIDATES"), cfg.int("CODE_GENERIC_LABEL_LISTS"),
                   cfg.int("CODE_GENERIC_LABEL_LEVEL_SIZE"))


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
    matched: str = "notation" # what the values matched: notation, label or notation+label
    languages: tuple = ()     # languages of the matched labels
    specific: int | None = None   # matched values that are notations or non-generic labels


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


def distinct_values(values) -> dict[str, list[tuple[str, str]]]:
    """A sample's distinct values (by their notation form, else label form) → their comparison forms."""
    out = {}
    for x in values:
        forms = value_forms(x)
        if forms:
            out.setdefault(forms[0][1], forms)
    return out


def scores(con, samples: dict[str, list[str]], generic_lists: int = 5,
           generic_level_size: int = 20) -> dict[str, list[tuple]]:
    """fingerprint → rows (list, scheme, version, level, containment, coverage, distinct, dense, matched,
    languages, specific) above zero. A value counts once however it matched (notation or label)."""
    rows = [(fp, v, kind, n) for fp, values in samples.items()
            for v, forms in distinct_values(values).items() for kind, n in forms]
    if not rows:
        return {}
    con.execute("CREATE OR REPLACE TEMP TABLE sv (fp VARCHAR, v VARCHAR, kind VARCHAR, n VARCHAR)")
    bulk.insert(con, "sv", ["fp", "v", "kind", "n"], rows)
    result = con.execute("""
        WITH n AS (SELECT fp, COUNT(DISTINCT v) AS k FROM sv GROUP BY fp),
        lvl AS (SELECT scheme, COALESCE(level, '') AS level, COUNT(DISTINCT norm) AS size,
                       COUNT(DISTINCT norm) FILTER (WHERE regexp_full_match(norm, '-?[0-9]+')) AS ints,
                       MIN(TRY_CAST(norm AS BIGINT)) AS lo, MAX(TRY_CAST(norm AS BIGINT)) AS hi
                FROM codes WHERE kind = 'notation' GROUP BY ALL),
        generic AS (SELECT c.norm FROM codes c JOIN lvl ON lvl.scheme = c.scheme AND lvl.level = COALESCE(c.level, '')
                    WHERE c.kind = 'label' AND c.version IS NULL GROUP BY c.norm
                    HAVING COUNT(DISTINCT c.list) >= ? AND median(lvl.size) <= ?),
        hits AS (SELECT sv.fp, c.list, c.scheme, c.version, COALESCE(c.level, '') AS level,
                        COUNT(DISTINCT sv.v) AS h,
                        COUNT(DISTINCT sv.v) FILTER (WHERE sv.kind = 'notation') AS hn,
                        COUNT(DISTINCT sv.v) FILTER (WHERE sv.kind = 'label') AS hl,
                        COUNT(DISTINCT sv.v) FILTER (WHERE sv.kind = 'notation'
                                                     OR sv.n NOT IN (SELECT norm FROM generic)) AS hs,
                        list_sort(list(DISTINCT c.lang) FILTER (WHERE c.lang IS NOT NULL)) AS langs
                 FROM sv JOIN codes c ON c.kind = sv.kind AND c.norm = sv.n
                 GROUP BY ALL)
        SELECT hits.fp, hits.list, hits.scheme, hits.version, hits.level,
               hits.h / n.k AS containment, hits.h / lvl.size AS coverage, n.k,
               (lvl.size = lvl.ints AND lvl.size >= 50 AND lvl.size >= 0.95 * (lvl.hi - lvl.lo + 1)) AS dense,
               CASE WHEN hits.hl = 0 THEN 'notation' WHEN hits.hn = 0 THEN 'label' ELSE 'notation+label' END,
               hits.langs, hits.hs
        FROM hits JOIN n USING (fp) JOIN lvl USING (scheme, level)""", [generic_lists, generic_level_size]).fetchall()
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
            rows = self.con.execute("SELECT DISTINCT TRY_CAST(norm AS BIGINT) AS n FROM codes WHERE kind = 'notation' AND scheme = ? "
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
    for lst, scheme, version, level, c, cov, k, dense, matched, langs, specific in rows:
        row = (lst, scheme, version, level, c, cov, k, bool(dense), matched, tuple(langs or ()), specific)
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
    ranked = sorted(best_list.values(), key=lambda r: (r[7], -r[4], r[8] == "label", -r[5], r[0]))
    hits = []
    for lst, scheme, version, level, c, cov, k, dense, matched, langs, specific in ranked:
        if c + EPS < t.candidate_min:
            continue
        # most specific entry the values support: a single version as good as the list
        tied = [r for r in by_version.get((lst, level), []) if r[4] + EPS >= c]
        if len(tied) == 1 and versions.get(lst, 0) > 1:
            _, scheme, version, _, c, cov, _, _, matched, langs, specific = tied[0]
        elif version is not None and len(tied) != 1:
            scheme, version = lst, None
        hits.append(Hit(lst, scheme, version, level or None, round(c, 4), round(cov, 4), k, dense, matched, langs,
                        specific))
    res = CodeResult(candidates=hits[:t.candidates])
    if not hits:
        res.reason = "no-list"
        return res
    best = hits[0]
    rivals = [h for h in hits[1:] if not h.dense and not (best.matched != "label" and h.matched == "label")]
    lead = best.containment - (rivals[0].containment if rivals else 0.0)
    if best.dense:
        res.reason = "dense-range"
    elif span and density and span[1] > span[0] and density(best.scheme, best.level, *span) + EPS >= RANGE_DENSITY:
        res.reason = "range-overlap"
    elif best.containment + EPS < t.min_containment:
        res.reason = "low-containment"
    elif best.distinct < t.min_distinct:
        res.reason = "few-values"
    elif best.specific is not None and best.specific < t.min_distinct:
        res.reason = "generic-labels"
    elif lead + EPS < t.min_lead:
        res.reason = "ambiguous"
    else:
        res.automatic = best
    return res


def match_all(codes_db, samples: dict[str, list[str]], t: Thresholds) -> dict[str, CodeResult]:
    con = duckdb.connect(str(codes_db), read_only=True)
    try:
        versions = versions_per_list(con)
        rows = scores(con, samples, t.generic_lists, t.generic_level_size)
        density = Density(con)
        return {fp: decide(rows.get(fp, []), versions, t, int_range(samples[fp]), density) for fp in samples}
    finally:
        con.close()
