"""Tree engine: nested JSON (genson) and XML (lxml path statistics, XSD types when available).

Objects and elements with children become nested sh:NodeShapes (Field.node);
leaves become typed fields with observed statistics. Cardinalities come from
the sample: minCount 1 when present in every parent instance, maxCount 1 when
never repeated.
"""
import json
import re
from collections import Counter
from pathlib import Path

from genson import SchemaBuilder
from lxml import etree

from ..model import CATEGORICAL_MAX, Field, Part, truncate_examples
from . import EngineError

MAX_DEPTH = 6
MAX_PROPS = 200
MAX_VALUES = 2000          # leaf values kept per path for statistics
XSD = "http://www.w3.org/2001/XMLSchema"
XSD_TYPES = {"string": "string", "normalizedString": "string", "token": "string", "anyURI": "string",
             "int": "integer", "integer": "integer", "long": "integer", "short": "integer", "byte": "integer",
             "nonNegativeInteger": "integer", "positiveInteger": "integer", "unsignedInt": "integer",
             "unsignedLong": "integer", "decimal": "number", "double": "number", "float": "number",
             "boolean": "boolean", "date": "date", "dateTime": "datetime", "time": "time", "gYear": "year",
             "gYearMonth": "yearmonth", "duration": "duration"}
INT = re.compile(r"^[+-]?\d+$")
NUM = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
DATE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_CH = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")
DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
BOOL = {"true", "false"}


class Stats:
    """Observed values and occurrence counts of one path, per parent instance."""

    def __init__(self):
        self.present = 0           # parent instances where the path occurs
        self.max_occurs = 0
        self.values = []
        self.nulls = 0
        self.objects = 0           # object values (array items included): the parents of nested paths

    def add(self, values: list):
        self.present += 1
        self.max_occurs = max(self.max_occurs, len(values))
        for v in values:
            if v is None or v == "":
                self.nulls += 1
            elif len(self.values) < MAX_VALUES:
                self.values.append(v)


def infer_type(values: list) -> tuple[str, str | None]:
    """Table Schema type (and format) of leaf values, text or JSON scalars."""
    vals = [v for v in values if v is not None and v != ""]
    if not vals:
        return "string", None
    if all(isinstance(v, bool) for v in vals):
        return "boolean", None
    if all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
        return "integer", None
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return "number", None
    s = [str(v).strip() for v in vals]
    if all(INT.match(x) for x in s):
        return "integer", None
    if all(NUM.match(x) for x in s):
        return "number", None
    if all(x.lower() in BOOL for x in s):
        return "boolean", None
    if all(DATE_ISO.match(x) for x in s):
        return "date", None
    if all(DATE_CH.match(x) for x in s):
        return "date", "%d.%m.%Y"
    if all(DATETIME.match(x) for x in s):
        return "datetime", None
    return "string", None


def leaf_stats(f: Field, st: Stats, parents: int) -> None:
    vals = st.values
    total = st.present + st.nulls if st.max_occurs <= 1 else len(vals) + st.nulls
    counter = Counter(str(v) for v in vals)
    f.stats = {"count": parents, "nullPercentage": round(100 * (1 - (st.present - min(st.nulls, st.present))
                                                                 / parents), 2) if parents else 0,
               "distinct": len(counter)}
    if f.type in ("integer", "number"):
        nums = [float(v) for v in vals if NUM.match(str(v).strip())]
        if nums:
            f.stats.update({"min": _n(min(nums)), "max": _n(max(nums)), "mean": sum(nums) / len(nums)})
    elif vals:
        s = sorted(str(v) for v in vals)
        f.stats.update({"min": s[0][:200], "max": s[-1][:200]})
    if 0 < len(counter) <= CATEGORICAL_MAX and len(counter) <= 0.2 * max(total, 1) and f.type != "number":
        f.categorical = True
        f.stats["values"] = sorted(counter)
    f.examples = truncate_examples(vals)


def _n(x: float):
    return int(x) if x.is_integer() else x


# --- JSON -----------------------------------------------------------------------------

def json_paths(value, pointer: str, stats: dict, depth: int):
    """Collect Stats for every pointer below an object instance."""
    if not isinstance(value, dict) or depth > MAX_DEPTH:
        return
    for k, v in list(value.items())[:MAX_PROPS]:
        p = f"{pointer}/{k}"
        items = v if isinstance(v, list) else [v]
        scalars = [x for x in items if not isinstance(x, (dict, list))]
        st = stats.setdefault(p, Stats())
        st.add(scalars if scalars or not items else [x for x in items])
        for x in items:
            if isinstance(x, dict):
                st.objects += 1
                json_paths(x, p, stats, depth + 1)


def json_part(schema: dict, pointer: str, stats: dict, parents: int, depth: int, label: str | None) -> Part:
    part = Part(label=label)
    required = set(schema.get("required", []))
    for order, (name, sub) in enumerate(list(schema.get("properties", {}).items())[:MAX_PROPS]):
        p = f"{pointer}/{name}"
        st = stats.get(p, Stats())
        types = _types(sub)
        is_array = "array" in types
        item = sub.get("items", {}) if is_array else sub
        item_types = _types(item) - {"null"}
        f = Field(name=name)
        f.minCount = 1 if name in required and "null" not in types and st.present >= parents else 0
        f.maxCount = None if is_array else 1
        if "object" in item_types and depth < MAX_DEPTH:
            f.type = "object"
            f.node = json_part(item, p, stats, max(st.objects, 1), depth + 1, name)
            f.stats = {"count": parents, "nullPercentage": round(100 * (1 - st.present / parents), 2)
                       if parents else 0}
        elif len(item_types) == 1 or item_types <= {"integer", "number"}:
            t = "number" if item_types == {"integer", "number"} else next(iter(item_types), "string")
            f.type = {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean"}.get(t, "any")
            if f.type == "string":
                f.type, f.format = infer_type([str(v) for v in st.values])
                if f.type in ("integer", "number", "boolean"):
                    f.type = "string"           # quoted numbers stay strings in JSON
            leaf_stats(f, st, parents)
        else:
            f.type = "any"
            leaf_stats(f, st, parents)
        if is_array:
            f.stats["maxItems"] = st.max_occurs
        part.fields.append(f)
    return part


def _types(schema: dict) -> set:
    if "anyOf" in schema:
        return set().union(*(_types(s) for s in schema["anyOf"]))
    t = schema.get("type", [])
    return set(t) if isinstance(t, list) else {t} if t else set()


def profile_json(path: Path, cfg) -> list[Part]:
    try:
        data = json.loads(path.read_bytes())
    except ValueError as e:
        raise EngineError(f"json-parse:{e}"[:120])
    if isinstance(data, dict) and data.get("type") in ("FeatureCollection", "Feature"):
        raise EngineError("skipped:geojson")
    rows = cfg.int("SAMPLE_ROWS")
    records = data[:rows] if isinstance(data, list) else [data]
    records = [r for r in records if isinstance(r, dict)]
    if not records:
        raise EngineError("json-without-objects")
    builder = SchemaBuilder()
    for r in records:
        builder.add_object(r)
    schema = builder.to_schema()
    stats = {}
    for r in records:
        json_paths(r, "", stats, 1)
    part = json_part(schema, "", stats, len(records), 1, None)
    part.rowCount = len(records)
    if isinstance(data, list):
        part.dialect = {"recordsPath": "/"}
    return [part]


# --- XML ------------------------------------------------------------------------------

def local(tag) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else str(tag)


class XNode:
    def __init__(self, name: str, ns: str | None):
        self.name, self.ns = name, ns
        self.instances = 0
        self.children: dict[str, "XNode"] = {}
        self.child_stats: dict[str, Stats] = {}
        self.attrs: dict[str, Stats] = {}
        self.text = Stats()
        self.has_children = False


def xml_walk(el, node: XNode, depth: int):
    node.instances += 1
    kids = [c for c in el if isinstance(c.tag, str)]
    node.has_children = node.has_children or bool(kids)
    for k, v in list(el.attrib.items())[:MAX_PROPS]:
        node.attrs.setdefault(local(k), Stats()).add([v])
    groups = {}
    for c in kids:
        groups.setdefault(local(c.tag), []).append(c)
    for name, els in list(groups.items())[:MAX_PROPS]:
        child = node.children.get(name)
        if child is None:
            child = node.children[name] = XNode(name, etree.QName(els[0].tag).namespace)
        st = node.child_stats.setdefault(name, Stats())
        texts = [(e.text or "").strip() if not any(isinstance(x.tag, str) for x in e) else None for e in els]
        st.add([t for t in texts if t is not None] or [None] * 0)
        st.max_occurs = max(st.max_occurs, len(els))
        if depth < MAX_DEPTH:
            for e in els:
                xml_walk(e, child, depth + 1)


def xml_part(node: XNode, xsd_types: dict, label: str) -> Part:
    part = Part(label=label)
    fields = []
    for name, st in node.attrs.items():
        f = Field(name=f"@{name}", minCount=1 if st.present >= node.instances else 0, maxCount=1)
        f.type, f.format = infer_type(st.values)
        leaf_stats(f, st, node.instances)
        fields.append(f)
    for name, child in node.children.items():
        st = node.child_stats[name]
        f = Field(name=name, minCount=1 if st.present >= node.instances else 0,
                  maxCount=1 if st.max_occurs <= 1 else None)
        if child.has_children:
            f.type = "object"
            f.node = xml_part(child, xsd_types, name)
            f.stats = {"count": node.instances, "nullPercentage": round(100 * (1 - st.present / node.instances), 2)}
        else:
            if child.attrs:              # a leaf with attributes is still a node
                f.node = xml_part(child, xsd_types, name)
            xsd = xsd_types.get(name)
            if xsd:
                f.type = xsd
            else:
                f.type, f.format = infer_type(st.values)
            leaf_stats(f, st, node.instances)
        if st.max_occurs > 1:
            f.stats["maxItems"] = st.max_occurs
        fields.append(f)
    part.fields = fields[:MAX_PROPS]
    return part


def xsd_simple_types(path: Path | None) -> dict:
    """Element name → Table Schema type, from a (local) XSD."""
    if not path or not path.exists():
        return {}
    try:
        doc = etree.parse(str(path), etree.XMLParser(recover=True, no_network=True))
    except etree.Error:
        return {}
    out = {}
    for el in doc.iter(f"{{{XSD}}}element"):
        name, typ = el.get("name"), el.get("type")
        if name and typ:
            t = XSD_TYPES.get(typ.split(":")[-1])
            if t:
                out.setdefault(name, t)
    return out


def profile_xml(path: Path, cfg, detail: dict) -> list[Part]:
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False, no_network=True)
    try:
        root = etree.parse(str(path), parser).getroot()
    except etree.Error as e:
        raise EngineError(f"xml-parse:{e}"[:120])
    if root is None:
        raise EngineError("xml-empty")
    ns = etree.QName(root.tag).namespace or ""
    if "rdf-syntax-ns" in ns:
        raise EngineError("routed:rdf")
    if "opengis.net/gml" in ns or "opengis.net/wfs" in ns:
        raise EngineError("routed:gml")
    node = XNode(local(root.tag), ns)
    xml_walk(root, node, 1)
    xsd = Path(str(path) + ".xsd")
    part = xml_part(node, xsd_simple_types(xsd if xsd.exists() else None), local(root.tag))
    part.rowCount = 1
    return [part]


def profile(path: Path, token: str, cfg, tmp: Path, detail: dict) -> list[Part]:
    if token in ("JSON", "JSONL"):
        return profile_json(Path(path), cfg)
    if token == "XML":
        return profile_xml(Path(path), cfg, detail)
    raise EngineError(f"tree-unsupported:{token}")
