"""The profile JSON interchange between `profile` and `emit`.

A superset of Frictionless Table Schema: a Structure holds Parts (one per
sheet, layer, class or table), a Part holds Fields with Table Schema `type` and
`constraints`, plus what was observed (`stats`, `examples`) and the hints the
emitter needs (key/measure role, units, nested node shapes).
"""
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

TEMPORAL = {"date", "datetime", "year", "yearmonth"}
NUMERIC = {"integer", "number"}
CATEGORICAL_MAX = 50       # at most this many distinct values for a code list
EXAMPLES_MAX = 3
EXAMPLE_CHARS = 200
VALUE_SAMPLE = 200         # distinct values kept per field for concept matching (VALUE_SAMPLE in pipeline.env)
SAMPLE_CHARS = 200


def structure_id(distribution_iri: str) -> str:
    return hashlib.sha256(distribution_iri.encode()).hexdigest()[:16]


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_").lower() or "field"


def unique_slugs(names: list[str]) -> list[str]:
    """Slugs, with a numeric suffix where two names collapse to the same one."""
    seen, out = {}, []
    for n in names:
        s = slug(n)
        if s in seen:
            seen[s] += 1
            s = f"{s}_{seen[s]}"
        else:
            seen[s] = 1
        out.append(s)
    return out


def truncate_examples(values) -> list[str]:
    out = []
    for v in values:
        if v is None:
            continue
        s = str(v)
        s = s if len(s) <= EXAMPLE_CHARS else s[:EXAMPLE_CHARS - 1] + "…"
        if s not in out:
            out.append(s)
        if len(out) == EXAMPLES_MAX:
            break
    return out


def sample_size(cfg) -> int:
    """VALUE_SAMPLE from the config; the default where an engine runs without one (tests)."""
    try:
        return cfg.int("VALUE_SAMPLE")
    except (AttributeError, KeyError, TypeError, ValueError):
        return VALUE_SAMPLE


def value_sample(values, n: int = VALUE_SAMPLE) -> list[str]:
    """Up to n distinct non-empty values as strings, truncated, chosen by their md5 hash.

    Deterministic: the same values give the same sample on every run and in every engine, so the
    slot fingerprint built from it is stable. Not part of the graph (out/slots.jsonl only)."""
    seen = set()
    for v in values:
        if v is None or isinstance(v, (dict, list)):
            continue
        s = str(v).strip()
        if s:
            seen.add(s if len(s) <= SAMPLE_CHARS else s[:SAMPLE_CHARS - 1] + "…")
    return sorted(seen, key=lambda s: hashlib.md5(s.encode()).hexdigest())[:n]


PATTERN_MIN_VALUES = 5     # distinct sample values needed before a shape is reported
PATTERN_COVERAGE = 0.95    # share of the sample values one shape must cover
REGEX_SPECIAL = set("\\.^$|?*+()[]{}-")


def _shape(value: str) -> list[tuple[str, str]]:
    """A value as runs of (class, text): "d" digits, "a" letters, "" one literal character."""
    runs = []
    for ch in value:
        cls = "d" if ch.isdigit() and ch.isascii() else "a" if ch.isalpha() else ""
        if cls and runs and runs[-1][0] == cls:
            runs[-1] = (cls, runs[-1][1] + ch)
        else:
            runs.append((cls, ch))
    return runs


def _letters(texts: list[str]) -> str:
    if not all(t.isascii() for t in texts):
        return r"\p{L}"
    if all(t.isupper() for t in texts):
        return "[A-Z]"
    if all(t.islower() for t in texts):
        return "[a-z]"
    return "[A-Za-z]"


def _repeat(lengths: list[int]) -> str:
    lo, hi = min(lengths), max(lengths)
    return "" if lo == hi == 1 else f"{{{lo}}}" if lo == hi else f"{{{lo},{hi}}}"


def _escape(text: str) -> str:
    """Escaped for XPath/SPARQL regex syntax (Python's re.escape also escapes characters XPath rejects)."""
    return "".join("\\" + c if c in REGEX_SPECIAL else c for c in text)


def value_pattern(values: list[str]) -> str | None:
    """The shape shared by nearly all values as an anchored regex (XPath syntax, as sh:pattern), or None.

    Values are cut into runs of digits, letters and single other characters. The most common sequence
    of run kinds must cover PATTERN_COVERAGE of the values. A run that is the same text in every value
    stays literal (`CHE`, `-`); otherwise digits become \\d and letters a class, with the observed
    length range: CHE-123.456.789 → ^CHE-\\d{3}\\.\\d{3}\\.\\d{3}$. Whether a shape is specific
    enough to say anything is concept matching's decision, not this one's."""
    values = [v for v in values if v and not v.endswith("…")]      # truncated values have lost their shape
    if len(values) < PATTERN_MIN_VALUES:
        return None
    groups: dict[tuple, list] = {}
    for v in values:
        runs = _shape(v)
        kinds = tuple(cls or text for cls, text in runs)       # a literal character is its own kind
        groups.setdefault(kinds, []).append(runs)
    kinds, members = max(groups.items(), key=lambda kv: (len(kv[1]), kv[0]))
    if len(members) < PATTERN_COVERAGE * len(values):
        return None
    out = []
    for i, kind in enumerate(kinds):
        texts = [runs[i][1] for runs in members]
        if len(set(texts)) == 1:
            out.append(_escape(texts[0]))
        elif kind == "d":
            out.append(r"\d" + _repeat([len(t) for t in texts]))
        else:
            out.append(_letters(texts) + _repeat([len(t) for t in texts]))
    return "^" + "".join(out) + "$"


@dataclass
class Field:
    name: str
    type: str = "any"                 # Table Schema type, plus "object" / "array"
    title: str | None = None
    description: str | None = None
    format: str | None = None
    path: str | None = None           # predicate IRI; None → minted column path
    datatype: str | None = None       # datatype IRI overriding the type mapping
    nodeKind: str | None = None       # IRI, BlankNode, Literal, ...
    cls: str | None = None            # sh:class
    constraints: dict = field(default_factory=dict)
    categorical: bool = False
    booleanCandidate: bool = False
    role: str | None = None           # key / measure, cube parts only
    unit: str | None = None           # qudt unit IRI
    unitLabel: str | None = None      # unit as published, when it doesn't map
    minCount: int | None = None       # explicit cardinality (tree, rdf); else derived
    maxCount: int | None = None
    node: "Part | None" = None        # nested object (tree engine)
    codeLabels: dict = field(default_factory=dict)   # code → {lang: label}
    stats: dict = field(default_factory=dict)        # count, nullPercentage, distinct, min, ...
    examples: list = field(default_factory=list)
    sample: list = field(default_factory=list)       # value_sample(): input of concept matching
    pattern: str | None = None                       # value_pattern() of a string field's sample

    def is_key(self, primary_key: list[str]) -> bool:
        """Key dimension: primary key, temporal, or categorical non-numeric-measure field."""
        if self.role:
            return self.role == "key"
        if self.name in primary_key or self.type in TEMPORAL:
            return True
        return self.categorical and self.type in ("string", "integer", "boolean")


@dataclass
class Part:
    slug: str = "main"
    label: str | None = None
    rowCount: int | None = None
    rowCountIsMinimum: bool | None = None            # True: the source has more rows than rowCount
    dialect: dict = field(default_factory=dict)      # delimiter, header, encoding, skipRows, headerRowCount
    geometryType: str | None = None
    crs: str | None = None                           # EPSG code, e.g. "2056"
    targetClass: str | None = None                   # rdf engine
    tableName: str | None = None                     # sheet or layer name in a multi-table source
    primaryKey: list = field(default_factory=list)
    keysUnique: bool | None = None                   # sample check, set by the engine
    cube: bool | None = None                         # True forces (PX), None → rule
    # Observed in the sample (tabular and geo engines), never constraints: field names unique and
    # present in every row, and single-column functional dependencies
    # {"determinant", "dependents", "rows", "distinct"} (see engines/tabular.dependencies).
    candidateKeys: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    fields: list[Field] = field(default_factory=list)

    def key_fields(self) -> list[Field]:
        return [f for f in self.fields if f.is_key(self.primaryKey)]

    def is_cube(self) -> bool:
        """cube:Constraint only when the key/measure split is confident."""
        if self.cube is not None:
            return self.cube
        keys = self.key_fields()
        measures = [f for f in self.fields if f not in keys and f.type in NUMERIC]
        return bool(keys and measures and self.keysUnique)


@dataclass
class Structure:
    id: str
    dataset: str
    representative: str
    distributions: list = field(default_factory=list)
    url: str | None = None
    declared: list = field(default_factory=list)
    sniffed: str | None = None
    formatMatch: bool | None = None
    status: str = "profiled"            # profiled / skipped / failed
    statusReason: str | None = None
    engine: str | None = None
    seconds: float | None = None
    parts: list[Part] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(_prune(asdict(self)), indent=1, ensure_ascii=False, default=str)

    def write(self, directory: Path) -> Path:
        path = directory / f"{self.id}.json"
        path.write_text(self.to_json())
        return path

    @classmethod
    def from_dict(cls, d: dict) -> "Structure":
        s = _build(cls, d)
        s.parts = [_part(p) for p in d.get("parts", [])]
        return s

    @classmethod
    def read(cls, path: Path) -> "Structure":
        return cls.from_dict(json.loads(path.read_text()))


def _part(d: dict) -> Part:
    p = _build(Part, d)
    p.fields = [_field(f) for f in d.get("fields", [])]
    return p


def _field(d: dict) -> Field:
    f = _build(Field, d)
    f.node = _part(d["node"]) if d.get("node") else None
    return f


def _build(cls, d: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


FLAGS = {"categorical", "booleanCandidate"}   # False is the default; meaningless when written


def _prune(v):
    """Drop None, empty values and unset flags to keep the JSON readable."""
    if isinstance(v, dict):
        return {k: _prune(x) for k, x in v.items()
                if x is not None and x != [] and x != {} and not (k in FLAGS and x is False)}
    if isinstance(v, list):
        return [_prune(x) for x in v]
    return v
