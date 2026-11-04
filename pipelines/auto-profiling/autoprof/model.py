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
    dialect: dict = field(default_factory=dict)      # delimiter, header, encoding, skipRows, headerRowCount
    geometryType: str | None = None
    crs: str | None = None                           # EPSG code, e.g. "2056"
    targetClass: str | None = None                   # rdf engine
    primaryKey: list = field(default_factory=list)
    keysUnique: bool | None = None                   # sample check, set by the engine
    cube: bool | None = None                         # True forces (PX), None → rule
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
