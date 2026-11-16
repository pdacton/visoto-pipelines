"""link-concepts: slots → data element concepts and data elements (phase 3, 3b) → out/links.jsonl.

Per table (dataset + container), largest first:
1. describe the whole table: dataset context (every language), distribution title, all columns,
   candidate row keys and functional dependencies (auto-profiling's containers.jsonl), and in detail
   the columns still without an answer (sample, value domain, code-list candidates);
2. look up the nearest existing object classes (for the table) and properties (per column) in the
   embedding index over the registry;
3. a model names each column's object class and property (each existing or new) or answers "none",
   and picks among ambiguous code-list candidates. The object class follows the rule in SYSTEM_PROMPT:
   the entity whose key determines the column, so one table can hold several;
4. a value check drops a code-list choice the data contradicts;
5. new object classes and properties go into the registry with status candidate and provenance,
   visible to the next lookup of the same run.
Data element concepts (object class + property) and data elements (concept + value domain) follow
by rule.

Two caches, so a rerun only asks what is new:
- per fingerprint (cache/concept-answers.jsonl): property, code-list choice, "none";
- per fingerprint and table (cache/object-class-answers.jsonl): the object class. The same column in
  two tables can describe different entities (a `geom` column is the geometry of whatever the rows
  are). Dataset context is in no key: an edited description causes no new call.
Answers in concept-answers.jsonl from before phase 3b also carry an object class; it is ignored.

Which model answers is open (open-questions.md: model, and whether sample values may go to a
hosted API). Models here: `none` (default: no concepts) and `answers` (answers/*.jsonl, written by a
person or by a model run outside this pipeline, keyed by fingerprint), and `claude` (Anthropic's
Messages API; needs CONCEPT_ALLOW_HOSTED=yes and `uv sync --group llm`). Every run writes the
questions it could not answer to out/concept-requests.jsonl.
"""
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Protocol

from . import linkvalues
from . import slots as slotio
from .config import Config
from .log import log
from .registry import CANDIDATE, Registry, id_segment, opaque_id

DIM = 1024


# --- embedding index ----------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    s = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    words = re.findall(r"[a-z0-9]+", s)
    grams = [w[i:i + 3] for w in words for i in range(max(1, len(w) - 2))]
    return words + grams


class HashingEmbedder:
    """Local, dependency-free embedding: hashed word and character-trigram counts, L2-normalised.
    A baseline until the embedding model is decided (multilingual, local or hosted)."""

    def embed(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for t in _tokens(text):
            h = int(hashlib.md5(t.encode()).hexdigest()[:8], 16)
            v[h % DIM] += 1.0 if h & 1 << 31 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


class Index:
    """Nearest registry entries of one kind by cosine similarity."""

    def __init__(self, embedder):
        self.embedder = embedder
        self.items: list[tuple[dict, list[float]]] = []

    def add(self, entry: dict) -> None:
        text = " ".join(list((entry.get("title") or {}).values()) + list((entry.get("description") or {}).values()))
        self.items.append((entry, self.embedder.embed(text)))

    def nearest(self, text: str, k: int) -> list[tuple[dict, float]]:
        q = self.embedder.embed(text)
        scored = [(e, sum(a * b for a, b in zip(q, v))) for e, v in self.items]
        return sorted(scored, key=lambda x: -x[1])[:k]


# --- models ---------------------------------------------------------------------------

class Model(Protocol):
    def answer(self, request: dict) -> dict | None:
        """A table request → {"columns": [column answer, ...]} (each with its "fingerprint"), or None."""


class NoModel:
    """No concepts are found or created (the default until a model is decided)."""

    def answer(self, request: dict) -> dict | None:
        return None


def table_key(dataset: str, container: str) -> str:
    return f"{dataset}|{container}"


class AnswersModel:
    """Answers from answers/*.jsonl, written by a person or by a model run outside this pipeline.

    A line with a "table" ({"dataset", "container"}) answers one column of that table: its object class,
    and its property unless the fingerprint has one already. A line without "table" (phase 3 format,
    keyed by fingerprint) gives the property, code-list choice or "none"; its object class is ignored."""

    def __init__(self, directory: Path):
        self.by_fp, self.by_table = {}, {}
        for path in sorted(directory.glob("*.jsonl")) if directory.exists() else []:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    a = json.loads(line)
                    if a.get("table"):
                        t = a["table"]
                        self.by_table[(table_key(t["dataset"], t["container"]), a["fingerprint"])] = a
                    else:
                        self.by_fp[a["fingerprint"]] = a

    def answer(self, request: dict) -> dict | None:
        key = table_key(request["table"]["dataset"], request["table"]["container"])
        out = []
        for col in request["ask"]:
            fp = col["fingerprint"]
            t, f = self.by_table.get((key, fp)), self.by_fp.get(fp)
            if f and f.get("none") or t and t.get("none"):
                out.append({"fingerprint": fp, "none": True, "rationale": (t or f).get("rationale"),
                            "model": (t or f).get("model")})
            elif t:
                a = {k: v for k, v in t.items() if k != "table"}
                if not a.get("property") and f:
                    a["property"] = f.get("property")
                    a.setdefault("codeList", f.get("codeList"))
                out.append(a)
            elif f and col.get("knownProperty") is None:
                out.append({**{k: v for k, v in f.items() if k != "objectClass"}, "propertyOnly": True})
        return {"columns": out} if out else None


PART_SCHEMA = {
    "type": "object",
    "properties": {
        "iri": {"type": ["string", "null"], "description": "IRI of an existing entry from the nearest list, or null"},
        "title": {"type": ["string", "null"], "description": "English label of a new entry (when iri is null)"},
        "description": {"type": ["string", "null"], "description": "English definition of a new entry"},
        "closeMatch": {"type": "array", "items": {"type": "string"},
                       "description": "ontology terms the new entry corresponds to, e.g. http://schema.org/Person"},
    },
    "required": ["iri", "title", "description", "closeMatch"],
    "additionalProperties": False,
}
COLUMN_SCHEMA = {
    "type": "object",
    "properties": {
        "fingerprint": {"type": "string", "description": "the fingerprint of the column answered"},
        "none": {"type": "boolean", "description": "true when the column carries no meaningful concept"},
        "objectClass": PART_SCHEMA,
        "property": PART_SCHEMA,
        "codeList": {"type": ["string", "null"], "description": "IRI of the fitting code-list candidate, or null"},
        "confidence": {"type": "number", "description": "0 to 1"},
        "rationale": {"type": "string"},
    },
    "required": ["fingerprint", "none", "objectClass", "property", "codeList", "confidence", "rationale"],
    "additionalProperties": False,
}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"columns": {"type": "array", "items": COLUMN_SCHEMA}},
    "required": ["columns"],
    "additionalProperties": False,
}
SYSTEM_PROMPT = """You build a metadata registry following ISO/IEC 11179 from the columns of open government \
datasets (Switzerland; names and values in German, French, Italian or English).

You get one table: the dataset's title, description and keywords in every language it is published in, the \
distribution's title, all columns with datatype and pattern, the candidate row keys, and the functional \
dependencies observed in a sample of rows (determinant -> dependents: each value of the determinant comes \
with one value of each dependent). The columns to answer ("ask") come with a value sample, their value domain \
if known, code-list candidates and the nearest existing properties; the nearest existing object classes are \
given once for the table.

For every column to answer, name its object class and its property:
- The object class is the entity whose key determines the column:
  - A column that depends only on the row key belongs to the table's own entity.
  - A key that points to another entity belongs to the referencing entity: "wohngemeinde_bfs" in a table \
of persons is Person + "municipality of residence" (the municipality itself is in the value domain).
  - Columns that depend on such a key belong to the referenced entity: "gemeinde_name" next to it is \
Municipality + "name".
  Columns of one table can have different object classes, and a column name seen in other tables can \
describe a different entity here (a geometry column is the geometry of whatever this table's rows are). \
Use the dependencies as evidence together with the names and the dataset description; a dependency \
observed in a sample can be accidental, and a code and its label determine each other.
- The property is the characteristic the column holds. Be specific: "municipality of residence" and \
"municipality of work" are different properties.
- When a column comes with "knownProperty", keep that property (give its iri) and decide only the \
object class.
- Reuse an existing entry (give its iri) when it means the same; otherwise leave iri null and give an \
English title, a one-sentence definition, and ontology terms it corresponds to if you know them.
- If the column carries no meaning of its own (technical ids such as objectid or gml_id, empty columns, \
layout artefacts), answer none = true.
- If code-list candidates are given, set codeList to the one whose meaning fits the column, or null.
Answer every column in "ask", identified by its fingerprint, with a confidence between 0 and 1 and a \
one-sentence rationale."""


class ClaudeModel:
    """Asks Claude (Messages API) per table; the answer follows ANSWER_SCHEMA.

    Sends the table description, including up to 30 sample values per asked column, to Anthropic's hosted
    API, so it runs only with CONCEPT_ALLOW_HOSTED=yes (open question: may sample values leave the machine?)."""

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium", client=None):
        if client is None:
            import anthropic          # optional dependency: uv sync --group llm
            client = anthropic.Anthropic()
        self.client, self.model, self.effort = client, model, effort
        self.calls = 0

    def answer(self, request: dict) -> dict | None:
        self.calls += 1
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=32000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                      # re-run a policy decline on a fallback model
            system=SYSTEM_PROMPT,
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
            messages=[{"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
        )
        if response.stop_reason != "end_turn":          # refusal or max_tokens: leave it as a request
            log(f"link-concepts: table {request['table']} not answered ({response.stop_reason})")
            return None
        data = json.loads(next(b.text for b in response.content if b.type == "text"))
        return {"columns": [to_answer(c, self.model) for c in data.get("columns", [])]}


def to_answer(data: dict, model: str) -> dict:
    """COLUMN_SCHEMA output → the answer format the linker reads ({"iri"} or {"new": {...}} per part)."""
    def part(p: dict | None) -> dict | None:
        if not p:
            return None
        if p.get("iri"):
            return {"iri": p["iri"]}
        if p.get("title"):
            return {"new": {"title": {"en": p["title"]},
                            "description": {"en": p["description"]} if p.get("description") else {},
                            "closeMatch": [c for c in p.get("closeMatch") or [] if re.match(r"^https?://", c)]}}
        return None
    fp = data.get("fingerprint")
    if data.get("none"):
        return {"fingerprint": fp, "none": True, "rationale": data.get("rationale"), "model": model}
    return {"fingerprint": fp, "objectClass": part(data.get("objectClass")), "property": part(data.get("property")),
            "codeList": data.get("codeList"), "confidence": max(0.0, min(1.0, float(data.get("confidence", 0)))),
            "rationale": data.get("rationale"), "model": model}


def model_from_config(cfg: Config) -> Model:
    name = cfg["CONCEPT_MODEL"]
    if name == "none":
        return NoModel()
    if name == "answers":
        return AnswersModel(cfg.pipeline_dir / "answers")
    if name == "claude":
        if cfg.values.get("CONCEPT_ALLOW_HOSTED") != "yes":
            raise SystemExit("link-concepts: CONCEPT_MODEL=claude sends sample values to Anthropic's API; "
                             "set CONCEPT_ALLOW_HOSTED=yes once that is decided (open-questions.md)")
        return ClaudeModel(cfg.values.get("CONCEPT_CLAUDE_MODEL") or "claude-opus-5-5",
                           cfg.values.get("CONCEPT_EFFORT") or "medium")
    raise SystemExit(f"link-concepts: unknown CONCEPT_MODEL {name!r} (none, answers, claude)")


# --- the stage ----------------------------------------------------------------------

ASK_MAX = 40          # columns asked per request; wider tables are asked in parts, each with the whole table
TABLE_SAMPLE = 5      # values per column in the table overview
ASK_SAMPLE = 30       # values per asked column


def first_text(texts: dict | None) -> str:
    """One text of a language map (de, fr, it, en, then any), for lookups."""
    texts = texts or {}
    return next((texts[l] for l in ("de", "fr", "it", "en", "") if texts.get(l)), next(iter(texts.values()), ""))


def entry_brief(e: dict, score: float) -> dict:
    return {"iri": e["iri"], "title": e.get("title"), "description": e.get("description"), "similarity": round(score, 3)}


class Table:
    """One table (dataset + container) of the input: its slots and auto-profiling's container record."""

    def __init__(self, dataset: str, container: str, slots: list[dict], record: dict | None):
        self.dataset, self.container, self.slots = dataset, container, slots
        self.key = table_key(dataset, container)
        self.record = record or {}

    def label(self) -> str:
        c = self.slots[0].get("container") or {}
        return c.get("label") or c.get("tableName") or c.get("path") or self.container

    def columns(self, value_domain=None) -> list[dict]:
        """All columns in order: from the container record, else from the slots; with each column's
        value domain title when value_domain (slot → title) is given."""
        by_name = {s["name"]: s for s in self.slots}
        cols = self.record.get("columns") or [{"name": s["name"], "datatype": s.get("datatype"),
                                                "pattern": s.get("pattern")} for s in self.slots]
        out = []
        for c in cols:
            s = by_name.get(c["name"]) or {}
            col = {"name": c["name"], "label": c.get("label"), "datatype": c.get("datatype"),
                   "pattern": c.get("pattern"), "sample": (s.get("sample") or [])[:TABLE_SAMPLE]}
            if value_domain and s and value_domain(s):
                col["valueDomain"] = value_domain(s)
            out.append(col)
        return out

    def describe(self, value_domain=None) -> dict:
        ds = self.record.get("dataset") or {}
        return {"table": {"dataset": self.dataset, "container": self.container},
                "datasetContext": {k: ds[k] for k in ("title", "description", "keywords", "themes") if ds.get(k)},
                "distributionTitle": (self.record.get("distribution") or {}).get("title"),
                "label": self.label(), "rowCount": self.record.get("rowCount"),
                "columns": self.columns(value_domain),
                "candidateKeys": self.record.get("candidateKeys") or [],
                "dependencies": [{"determinant": d["determinant"], "dependents": d["dependents"],
                                  "rows": d.get("rows"), "distinct": d.get("distinct")}
                                 for d in self.record.get("dependencies") or []]}

    def lookup_text(self) -> str:
        ds = self.record.get("dataset") or {}
        return " ".join(filter(None, [self.label(), (self.record.get("distribution") or {}).get("title"),
                                      first_text(ds.get("title"))]))

    def referenced(self) -> set[str]:
        """Source names that depend on a determinant other than a candidate key (another entity's attributes)."""
        keys = set(self.record.get("candidateKeys") or [])
        return {d for dep in self.record.get("dependencies") or [] if dep["determinant"] not in keys
                for d in dep["dependents"]}


def tables_of(slots: list[dict], containers: dict[str, dict]) -> list[Table]:
    """Slots grouped by table, largest first (the same order on every run)."""
    groups: dict[tuple, list] = {}
    for s in slots:
        dataset, container, _ = slotio.key_of(s)
        groups.setdefault((dataset, container), []).append(s)
    tables = [Table(d, c, ss, containers.get((ss[0].get("container") or {}).get("iri")))
              for (d, c), ss in groups.items()]
    return sorted(tables, key=lambda t: (-len(t.slots), t.key))


class Linker:
    def __init__(self, cfg: Config, reg: Registry, model: Model, embedder=None):
        self.cfg, self.reg, self.model = cfg, reg, model
        self.embedder = embedder or HashingEmbedder()
        self.classes, self.properties = Index(self.embedder), Index(self.embedder)
        for e in reg.all("objectclasses"):
            self.classes.add(e)
        for e in reg.all("properties"):
            self.properties.add(e)
        self.prop_path = cfg.cache / "concept-answers.jsonl"
        self.oc_path = cfg.cache / "object-class-answers.jsonl"
        self.props = {a["fingerprint"]: a for a in self._read(self.prop_path)}
        self.ocs = {(table_key(a["table"]["dataset"], a["table"]["container"]), a["fingerprint"]): a
                    for a in self._read(self.oc_path)}
        self.requests: list[dict] = []
        self.calls = 0
        self.run = linkvalues.run_iri(cfg)
        self.min_conf = cfg.float("CONCEPT_MIN_CONFIDENCE")
        self.nearest = cfg.int("NEAREST")

    @staticmethod
    def _read(path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def _append(self, path: Path, record: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # --- requests --------------------------------------------------------------------

    def settled(self, table: Table, fp: str) -> bool:
        p = self.props.get(fp)
        return bool(p) and (p.get("none") or (table.key, fp) in self.ocs)

    def ask_column(self, slot: dict, rec: dict) -> dict:
        vd = self.reg.get("valuedomains", rec["valueDomain"]) if rec.get("valueDomain") else None
        codes = [{"iri": c["entry"], "title": (self.reg.get("valuedomains", c["entry"]) or {}).get("title"),
                  "containment": c["evidence"].get("containment"), "matched": c["evidence"].get("matched")}
                 for c in rec["candidates"] if c["evidence"]["method"] == "code-overlap"]
        known = self.props.get(slot["fingerprint"])
        prop = self.resolve("properties", known.get("property"), slot["fingerprint"], slot, create=False) \
            if known else None
        text = " ".join(filter(None, [slot["name"], slot.get("label") or ""]))
        col = {"fingerprint": slot["fingerprint"], "name": slot["name"], "label": slot.get("label"),
               "description": slot.get("description"), "datatype": slot.get("datatype"),
               "unit": slot.get("unit") or slot.get("unitLabel"), "pattern": slot.get("pattern"),
               "sample": (slot.get("sample") or [])[:ASK_SAMPLE],
               "valueDomain": {"iri": vd["iri"], "title": vd.get("title")} if vd else None,
               "codeCandidates": codes}
        if prop:
            col["knownProperty"] = {"iri": prop["iri"], "title": prop.get("title")}
        else:
            col["nearestProperties"] = [entry_brief(e, s) for e, s in self.properties.nearest(text, self.nearest)]
        return col

    def request(self, table: Table, ask: list[dict], by_slot: dict) -> dict:
        def vd_title(slot: dict) -> str | None:
            e = self.reg.get("valuedomains", by_slot[slot["iri"]].get("valueDomain") or "")
            return first_text(e.get("title")) or e.get("id") if e else None
        return {**table.describe(vd_title),
                "nearestObjectClasses": [entry_brief(e, s) for e, s in
                                         self.classes.nearest(table.lookup_text(), self.nearest)],
                "ask": [self.ask_column(s, by_slot[s["iri"]]) for s in ask]}

    def store(self, table: Table, a: dict) -> None:
        """One column answer → the fingerprint cache (if new there) and the table's object-class cache."""
        fp = a.get("fingerprint")
        if not fp:
            return
        if fp not in self.props:
            p = {k: a.get(k) for k in ("none", "property", "codeList", "confidence", "rationale", "model")
                 if a.get(k) is not None}
            if p.get("none") or p.get("property"):
                self.props[fp] = {"fingerprint": fp, **p}
                self._append(self.prop_path, self.props[fp])
        elif a.get("codeList") and not self.props[fp].get("codeList") and not self.props[fp].get("none"):
            # a code-list choice for a column whose property was known (new candidates, e.g. from labels)
            self.props[fp] = {**self.props[fp], "codeList": a["codeList"]}
            self._append(self.prop_path, self.props[fp])
        if a.get("objectClass") and not a.get("none") and (table.key, fp) not in self.ocs:
            oc = {"fingerprint": fp, "table": {"dataset": table.dataset, "container": table.container},
                  "objectClass": a["objectClass"], "confidence": a.get("confidence"),
                  "rationale": a.get("rationale"), "model": a.get("model")}
            self.ocs[(table.key, fp)] = oc
            self._append(self.oc_path, oc)

    def ask(self, table: Table, by_slot: dict) -> None:
        seen, todo = set(), []
        for s in table.slots:
            fp = s["fingerprint"]
            if fp not in seen and not self.settled(table, fp):
                seen.add(fp)
                todo.append(s)
        for i in range(0, len(todo), ASK_MAX):
            chunk = todo[i:i + ASK_MAX]
            req = self.request(table, chunk, by_slot)
            self.calls += 1
            ans = self.model.answer(req)
            for a in (ans or {}).get("columns", []):
                self.store(table, a)
            left = [c for c in req["ask"] if not self.settled(table, c["fingerprint"])]
            if left:
                self.requests.append({**req, "ask": left})

    # --- registry entries --------------------------------------------------------------

    def resolve(self, kind: str, part: dict | None, fp: str, slot: dict, create: bool = True) -> dict | None:
        """An answer part ({"iri"} or {"new": {title, description, closeMatch}}) → registry entry."""
        if not part:
            return None
        if part.get("iri"):
            return self.reg.get(kind, part["iri"])
        new = part.get("new")
        if not new or not (new.get("title") or {}).get("en"):
            return None
        title = new["title"]["en"].strip().lower()
        same = next((e for e in self.reg.all(kind) if (e.get("title") or {}).get("en", "").strip().lower() == title), None)
        if same or not create:        # an entry with this exact title exists: reuse it, no duplicate
            return same
        ident = opaque_id(kind, title, fp)
        entry = self.reg.put(kind, {"iri": self.reg.iri(kind, ident), "id": ident, "title": new["title"],
                                    "description": new.get("description") or {}, "status": CANDIDATE,
                                    "closeMatch": new.get("closeMatch") or [], "generatedBy": self.run,
                                    "derivedFrom": [slot["iri"]]})
        (self.classes if kind == "objectclasses" else self.properties).add(entry)
        return entry

    def concept(self, oc: dict, prop: dict, slot: dict) -> dict:
        ident = f"{oc['id']}-{prop['id']}"
        title = {lang: f"{prop['title'][lang]} ({oc['title'].get(lang) or oc['title']['en']})"
                 for lang in prop["title"] if lang in oc["title"] or lang == "en"}
        return self.reg.put("dataelementconcepts", {
            "iri": self.reg.iri("dataelementconcepts", id_segment(ident)), "id": ident, "title": title,
            "objectClass": oc["iri"], "property": prop["iri"], "status": CANDIDATE, "generatedBy": self.run,
            "derivedFrom": [slot["iri"]]})

    def data_element(self, dec: dict, vd: dict) -> dict:
        ident = f"{dec['id']}--{id_segment(vd['id'])}"
        prop = self.reg.get("properties", dec["property"]) or {}
        path = (prop.get("closeMatch") or [None])[0] or dec["property"]
        title = {"en": f"{dec['title'].get('en', dec['id'])} – {vd['title'].get('en', vd['id'])}"}
        return self.reg.put("dataelements", {
            "iri": self.reg.iri("dataelements", id_segment(ident)), "id": ident, "title": title,
            "dataElementConcept": dec["iri"], "valueDomain": vd["iri"], "path": path,
            "status": CANDIDATE if dec.get("status") == CANDIDATE else "Completed", "generatedBy": self.run})

    # --- linking -----------------------------------------------------------------------

    def link(self, slots: list[dict], links: list[dict], containers: dict[str, dict] | None = None) -> list[dict]:
        by_slot = {r["slot"]: r for r in links}
        for table in tables_of(slots, containers or {}):
            self.ask(table, by_slot)
            for s in table.slots:
                self.apply(table, s, by_slot[s["iri"]])
        for rec in links:
            self.shortcuts(rec)
        return links

    def apply(self, table: Table, slot: dict, rec: dict) -> None:
        fp = slot["fingerprint"]
        p = self.props.get(fp)
        if p is None:
            return
        if p.get("none"):
            rec["notes"].append({"concept": "none"})
            return
        conf = float(p.get("confidence") or 0)
        evidence = {"method": "llm", "rationale": p.get("rationale")} if p.get("rationale") else {"method": "llm"}
        self.code_choice(rec, p.get("codeList"), conf, evidence)
        o = self.ocs.get((table.key, fp))
        if o is None:
            return
        oc = self.resolve("objectclasses", o.get("objectClass"), fp, slot)
        prop = self.resolve("properties", p.get("property"), fp, slot)
        if not (oc and prop):
            return
        dec = self.concept(oc, prop, slot)
        conf = min(conf, float(o.get("confidence") if o.get("confidence") is not None else conf))
        rationale = o.get("rationale") or p.get("rationale")
        evidence = {"method": "llm", "rationale": rationale} if rationale else {"method": "llm"}
        rec["candidates"].append({"entry": dec["iri"], "kind": "dataElementConcept", "rank": 1,
                                  "score": round(conf, 4), "evidence": evidence, "run": self.run})
        if not any(m["kind"] == "dataElementConcept" and m.get("person") for m in rec["matches"]) \
                and conf + 1e-9 >= self.min_conf:
            rec["matches"].append({"entry": dec["iri"], "kind": "dataElementConcept", "matchType": "exactMatch",
                                   "score": round(conf, 4), "by": self.run, "evidence": evidence})

    def code_choice(self, rec: dict, choice: str | None, conf: float, evidence: dict) -> None:
        """The model's pick among ambiguous code-list candidates, if the data supports it (value check)."""
        if not choice or any(m["kind"] == "valueDomain" and m.get("person") for m in rec["matches"]):
            return
        cand = next((c for c in rec["candidates"] if c["entry"] == choice and c["evidence"]["method"] == "code-overlap"),
                    None)
        if cand is None:
            rec["notes"].append({"dropped": choice, "why": "not a code-list candidate supported by the values"})
            return
        if conf + 1e-9 < self.min_conf:
            return
        rec["matches"] = [m for m in rec["matches"] if m["kind"] != "valueDomain"]
        rec["matches"].append({"entry": choice, "kind": "valueDomain", "matchType": "exactMatch",
                               "score": round(conf, 4), "by": self.run,
                               "evidence": {**evidence, **{k: cand["evidence"][k] for k in
                                                           ("containment", "matched", "languages")
                                                           if cand["evidence"].get(k) is not None}}})
        rec["valueDomain"] = choice

    def shortcuts(self, rec: dict) -> None:
        """Shortcuts from the winning matches (a person's first); the data element by rule."""
        for kind in ("valueDomain", "dataElementConcept", "dataElement"):
            ms = [m for m in rec["matches"] if m["kind"] == kind]
            if ms:
                rec[kind] = next((m for m in ms if m.get("person")), ms[-1])["entry"]
        if rec.get("dataElementConcept") and rec.get("valueDomain") and not rec.get("dataElement"):
            dec = self.reg.get("dataelementconcepts", rec["dataElementConcept"])
            vd = self.reg.get("valuedomains", rec["valueDomain"])
            if dec and vd:
                de = self.data_element(dec, vd)
                rec["matches"].append({"entry": de["iri"], "kind": "dataElement", "matchType": "exactMatch",
                                       "score": 1.0, "by": self.run, "evidence": {"method": "rule"}})
                rec["dataElement"] = de["iri"]


def main_object_classes(links: list[dict], slots: list[dict], reg: Registry,
                        containers: dict[str, dict] | None = None) -> dict[str, str]:
    """container → the object class of its own entity: the majority (at least half) among the slots that
    do not depend on another entity's key (auto-profiling's dependencies; all slots without them)."""
    tables = {t.slots[0]["container"]["iri"]: t for t in tables_of(slots, containers or {})
              if (t.slots[0].get("container") or {}).get("iri")}
    by_iri = {s["iri"]: s for s in slots}
    votes: dict[str, Counter] = {}
    for rec in links:
        s = by_iri.get(rec["slot"])
        dec = reg.get("dataelementconcepts", rec.get("dataElementConcept") or "")
        c = (s or {}).get("container", {}).get("iri")
        if not (dec and c):
            continue
        t = tables.get(c)
        if t and s["name"] in t.referenced():
            continue
        votes.setdefault(c, Counter())[dec["objectClass"]] += 1
    out = {}
    for c, v in votes.items():
        oc, n = v.most_common(1)[0]
        if n * 2 >= sum(v.values()):
            out[c] = oc
    return out


def run(cfg: Config) -> None:
    reg = Registry.load(cfg.registry_dir, cfg.base_iri)
    slots = slotio.load(slotio.input_path(cfg))
    containers = slotio.load_containers(cfg)
    links = linkvalues.read(cfg)
    linker = Linker(cfg, reg, model_from_config(cfg))
    links = linker.link(slots, links, containers)
    reg.save()
    linkvalues.write(cfg, links)
    with open(cfg.out / "concept-requests.jsonl", "w", encoding="utf-8") as f:
        for r in linker.requests:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (cfg.out / "main-object-classes.json").write_text(
        json.dumps(main_object_classes(links, slots, reg, containers), indent=1))
    n = Counter(k for r in links for k in ("dataElementConcept", "dataElement") if r.get(k))
    log(f"link-concepts: model {cfg['CONCEPT_MODEL']}; {dict(n)} slots linked; "
        f"{sum(len(r['ask']) for r in linker.requests)} columns in {len(linker.requests)} tables unanswered "
        f"→ out/concept-requests.jsonl")
