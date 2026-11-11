"""link-concepts: slots → data element concepts and data elements (phase 3) → out/links.jsonl.

Per fingerprint, most slots first:
1. describe the slot (name, label, container, neighbours, datatype, sample, value domain);
2. look up the nearest existing object classes and properties (embedding index over the registry);
3. a model names the object class and the property (each existing or new) or answers "none", and
   picks among ambiguous code-list candidates in the same answer;
4. a value check drops a code-list choice the data contradicts;
5. new object classes and properties go into the registry with status candidate and provenance,
   visible to the next lookup of the same run.
Data element concepts (object class + property) and data elements (concept + value domain) follow
by rule. Answers are cached by fingerprint, so a rerun only asks about new slots.

Which model answers is open (open-questions.md: model, and whether sample values may go to a
hosted API). Models here: `none` (default: no concepts) and `answers` (answers/*.jsonl, written by a
person or by a model run outside this pipeline, keyed by fingerprint). Every run writes the
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


# --- models -------------------------------------------------------------------------

class Model(Protocol):
    def answer(self, request: dict) -> dict | None: ...


class NoModel:
    """No concepts are found or created (the default until a model is decided)."""

    def answer(self, request: dict) -> dict | None:
        return None


class AnswersModel:
    """Answers from answers/*.jsonl, one JSON object per line with the request's `fingerprint`."""

    def __init__(self, directory: Path):
        self.answers = {}
        for path in sorted(directory.glob("*.jsonl")) if directory.exists() else []:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    a = json.loads(line)
                    self.answers[a["fingerprint"]] = a

    def answer(self, request: dict) -> dict | None:
        return self.answers.get(request["fingerprint"])


def model_from_config(cfg: Config) -> Model:
    name = cfg["CONCEPT_MODEL"]
    if name == "none":
        return NoModel()
    if name == "answers":
        return AnswersModel(cfg.pipeline_dir / "answers")
    raise SystemExit(f"link-concepts: unknown CONCEPT_MODEL {name!r} (none, answers)")


# --- the stage ----------------------------------------------------------------------

def describe(slot: dict, value_domain: dict | None, code_candidates: list[dict]) -> dict:
    c = slot.get("container") or {}
    return {"name": slot["name"], "label": slot.get("label"), "description": slot.get("description"),
            "container": c.get("label") or c.get("tableName") or c.get("path"), "neighbours": slot.get("neighbours"),
            "datatype": slot.get("datatype"), "unit": slot.get("unit") or slot.get("unitLabel"),
            "sample": (slot.get("sample") or [])[:30],
            "valueDomain": {"iri": value_domain["iri"], "title": value_domain.get("title")} if value_domain else None,
            "codeCandidates": code_candidates}


def entry_brief(e: dict, score: float) -> dict:
    return {"iri": e["iri"], "title": e.get("title"), "description": e.get("description"), "similarity": round(score, 3)}


class Linker:
    def __init__(self, cfg: Config, reg: Registry, model: Model, embedder=None):
        self.cfg, self.reg, self.model = cfg, reg, model
        self.embedder = embedder or HashingEmbedder()
        self.classes, self.properties = Index(self.embedder), Index(self.embedder)
        for e in reg.all("objectclasses"):
            self.classes.add(e)
        for e in reg.all("properties"):
            self.properties.add(e)
        self.cache_path = cfg.cache / "concept-answers.jsonl"
        self.cache = self._read_cache()
        self.requests: list[dict] = []
        self.run = linkvalues.run_iri(cfg)
        self.min_conf = cfg.float("CONCEPT_MIN_CONFIDENCE")
        self.nearest = cfg.int("NEAREST")

    def _read_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}
        out = {}
        for line in self.cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                a = json.loads(line)
                out[a["fingerprint"]] = a
        return out

    def _store(self, answer: dict) -> None:
        self.cache[answer["fingerprint"]] = answer
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(answer, ensure_ascii=False) + "\n")

    def request(self, fp: str, slot: dict, rec: dict) -> dict:
        vd = self.reg.get("valuedomains", rec["valueDomain"]) if rec.get("valueDomain") else None
        codes = [{"iri": c["entry"], "title": (self.reg.get("valuedomains", c["entry"]) or {}).get("title"),
                  "containment": c["evidence"].get("containment")}
                 for c in rec["candidates"] if c["evidence"]["method"] == "code-overlap"]
        d = describe(slot, vd, codes)
        text = " ".join(filter(None, [slot["name"], slot.get("label") or "", d["container"] or ""]))
        return {"fingerprint": fp, "slot": d,
                "nearestObjectClasses": [entry_brief(e, s) for e, s in self.classes.nearest(d["container"] or text,
                                                                                          self.nearest)],
                "nearestProperties": [entry_brief(e, s) for e, s in self.properties.nearest(text, self.nearest)]}

    def resolve(self, kind: str, part: dict | None, fp: str, slot: dict) -> dict | None:
        """An answer part ({"iri"} or {"new": {title, description, closeMatch}}) → registry entry."""
        if not part:
            return None
        if part.get("iri"):
            return self.reg.get(kind, part["iri"])
        new = part.get("new")
        if not new or not (new.get("title") or {}).get("en"):
            return None
        ident = opaque_id(kind, new["title"]["en"].strip().lower(), fp)
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

    def link(self, slots: list[dict], links: list[dict]) -> list[dict]:
        by_slot = {r["slot"]: r for r in links}
        groups = slotio.by_fingerprint(slots)
        for fp in sorted(groups, key=lambda f: (-len(groups[f]), f)):
            group = groups[fp]
            first = by_slot[group[0]["iri"]]
            ans = self.cache.get(fp)
            if ans is None:
                req = self.request(fp, group[0], first)
                ans = self.model.answer(req)
                if ans is None:
                    self.requests.append(req)
                    continue
                ans = {**ans, "fingerprint": fp}
                self._store(ans)
            if ans.get("none"):
                for s in group:
                    by_slot[s["iri"]]["notes"].append({"concept": "none"})
                continue
            oc = self.resolve("objectclasses", ans.get("objectClass"), fp, group[0])
            prop = self.resolve("properties", ans.get("property"), fp, group[0])
            dec = self.concept(oc, prop, group[0]) if oc and prop else None
            conf = float(ans.get("confidence", 0))
            evidence = {"method": "llm", "rationale": ans.get("rationale")} if ans.get("rationale") else {"method": "llm"}
            for s in group:
                rec = by_slot[s["iri"]]
                self.code_choice(rec, ans.get("codeList"), conf, evidence)
                if dec is None:
                    continue
                rec["candidates"].append({"entry": dec["iri"], "kind": "dataElementConcept", "rank": 1,
                                          "score": round(conf, 4), "evidence": evidence, "run": self.run})
                if not any(m["kind"] == "dataElementConcept" and m.get("person") for m in rec["matches"]) \
                        and conf + 1e-9 >= self.min_conf:
                    rec["matches"].append({"entry": dec["iri"], "kind": "dataElementConcept", "matchType": "exactMatch",
                                           "score": round(conf, 4), "by": self.run, "evidence": evidence})
        for rec in links:
            self.shortcuts(rec)
        return links

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
                               "evidence": {**evidence, "containment": cand["evidence"].get("containment")}})
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


def main_object_classes(links: list[dict], slots: list[dict], reg: Registry) -> dict[str, str]:
    """container → the object class most of its concept-linked slots share (at least half)."""
    container = {s["iri"]: (s.get("container") or {}).get("iri") for s in slots}
    votes: dict[str, Counter] = {}
    for rec in links:
        dec = reg.get("dataelementconcepts", rec.get("dataElementConcept") or "")
        if dec and container.get(rec["slot"]):
            votes.setdefault(container[rec["slot"]], Counter())[dec["objectClass"]] += 1
    out = {}
    for c, v in votes.items():
        oc, n = v.most_common(1)[0]
        if n * 2 >= sum(v.values()):
            out[c] = oc
    return out


def run(cfg: Config) -> None:
    reg = Registry.load(cfg.registry_dir, cfg.base_iri)
    slots = slotio.load(slotio.input_path(cfg))
    links = linkvalues.read(cfg)
    linker = Linker(cfg, reg, model_from_config(cfg))
    links = linker.link(slots, links)
    reg.save()
    linkvalues.write(cfg, links)
    with open(cfg.out / "concept-requests.jsonl", "w", encoding="utf-8") as f:
        for r in linker.requests:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (cfg.out / "main-object-classes.json").write_text(json.dumps(main_object_classes(links, slots, reg), indent=1))
    n = Counter(k for r in links for k in ("dataElementConcept", "dataElement") if r.get(k))
    log(f"link-concepts: model {cfg['CONCEPT_MODEL']}; {dict(n)} slots linked; "
        f"{len(linker.requests)} fingerprints unanswered → out/concept-requests.jsonl")
