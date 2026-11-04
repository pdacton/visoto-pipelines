"""PX engine: PC-Axis files (pyaxis) and PxWeb tables (API metadata) → cube:Constraint.

Every PX variable is a cube:KeyDimension with its codes as sh:in and labels per
language; the content variable (CONTVARIABLE), or a single "value" column when
there is none, gives the cube:MeasureDimension(s) with UNITS mapped to QUDT.
"""
import contextlib
import io
import json
import math
import re
from pathlib import Path

from ..model import Field, Part
from . import EngineError

QUDT_UNIT = "http://qudt.org/vocab/unit/"
UNITS = {  # lower-cased PX UNITS → QUDT unit
    "anzahl": "NUM", "number": "NUM", "nombre": "NUM", "numero": "NUM", "personen": "NUM",
    "persons": "NUM", "personnes": "NUM", "persone": "NUM", "%": "PERCENT", "prozent": "PERCENT",
    "percent": "PERCENT", "pour cent": "PERCENT", "per cento": "PERCENT", "in %": "PERCENT",
    "chf": "CCY_CHF", "franken": "CCY_CHF", "francs": "CCY_CHF", "franchi": "CCY_CHF",
    "eur": "CCY_EUR", "kg": "KiloGM", "tonnen": "TONNE", "tonnes": "TONNE", "t": "TONNE",
    "km": "KiloM", "km2": "KiloM2", "km²": "KiloM2", "ha": "HA", "hektaren": "HA", "m2": "M2", "m²": "M2",
    "m3": "M3", "m³": "M3", "jahre": "YR", "years": "YR", "ans": "YR", "anni": "YR", "kwh": "KiloW-HR",
    "mwh": "MegaW-HR", "gwh": "GigaW-HR", "tj": "TeraJ", "liter": "L", "l": "L",
}
TIME_NAMES = re.compile(r"^(jahr|year|année|annee|anno|stichtag|periode|period|période|zeit|time|"
                        r"quartal|quarter|trimestre|monat|month|mois|mese|datum|date)\b", re.I)
PX_LANG_PREFS = ["de", "fr", "it", "en", "rm"]


def unit_iri(label: str | None) -> str | None:
    if not label:
        return None
    key = label.strip().lower()
    key = re.sub(r"^(in|en)\s+", "", key) if key not in UNITS else key
    return QUDT_UNIT + UNITS[key] if key in UNITS else None


def time_kind(texts: list[str]) -> tuple[str, str | None]:
    """(Table Schema type, PX-ish time unit) from a time variable's value labels."""
    if texts and all(re.fullmatch(r"\d{4}", t.strip()) for t in texts):
        return "year", "year"
    if texts and all(re.fullmatch(r"\d{4}[MQ]\d{1,2}|\d{4}-\d{2}", t.strip()) for t in texts):
        return "string", "month" if "M" in texts[0] or "-" in texts[0] else "quarter"
    if texts and all(re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2}", t.strip()) for t in texts):
        return "string", "day"
    return "string", None


# --- readers: both give {title, languages, variables: [...], keywords: {...}} ------------------

def from_pxweb(directory: Path) -> dict:
    metas = {}
    for f in sorted(directory.glob("meta-*.json")):
        metas[f.stem.split("-", 1)[1]] = json.loads(f.read_text(encoding="utf-8"))
    if not metas:
        raise EngineError("pxweb-without-metadata")
    keywords = read_keywords(directory / "keywords.px") if (directory / "keywords.px").exists() else {}
    langs = sorted(metas, key=lambda l: PX_LANG_PREFS.index(l) if l in PX_LANG_PREFS else 99)
    main = metas[langs[0]]
    variables = []
    for i, v in enumerate(main["variables"]):
        labels = {}
        for lang in langs:
            other = metas[lang]["variables"]
            if i < len(other) and other[i]["values"] == v["values"]:
                labels[lang] = {"text": other[i]["text"], "valueTexts": other[i]["valueTexts"]}
        variables.append({"code": v["code"], "labels": labels, "values": v["values"],
                          "time": bool(v.get("time")), "elimination": bool(v.get("elimination"))})
    return {"title": {l: metas[l].get("title") for l in langs}, "languages": langs,
            "variables": variables, "keywords": keywords}


def px_encoding(path: Path) -> str:
    head = path.read_bytes()[:4096].decode("latin-1")
    m = re.search(r'CODEPAGE\s*=\s*"([^"]+)"', head)
    enc = (m.group(1) if m else "iso-8859-15").lower()
    return "utf-8" if "utf" in enc else enc


def read_keywords(path: Path) -> dict:
    from pyaxis import pyaxis
    try:
        with contextlib.redirect_stdout(io.StringIO()):     # pyaxis prints notices
            return pyaxis.parse(str(path), encoding=px_encoding(path))["METADATA"]
    except Exception:  # noqa: BLE001 - keywords are optional
        return {}


def from_px(path: Path) -> dict:
    meta = read_keywords(path)
    if not meta:
        raise EngineError("px-unparseable")
    lang = first(meta.get("LANGUAGE")) or "de"
    names = list(meta.get("STUB", [])) + list(meta.get("HEADING", []))
    variables = []
    for name in names:
        texts = list(meta.get(f"VALUES({name})", []))
        codes = list(meta.get(f"CODES({name})", [])) or texts
        labels = {lang: {"text": name, "valueTexts": texts}}   # pyaxis reads the default language only
        variables.append({"code": first(meta.get(f"VARIABLECODE({name})")) or name, "labels": labels,
                          "values": codes, "time": f"TIMEVAL({name})" in meta, "elimination": False})
    title = first(meta.get("TITLE")) or first(meta.get("DESCRIPTION"))
    return {"title": {lang: title}, "languages": [lang], "variables": variables, "keywords": meta}


def first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


# --- the part -----------------------------------------------------------------------

def build_part(table: dict) -> Part:
    kw = table["keywords"]
    langs = table["languages"]
    main = langs[0]
    contvar = first(kw.get("CONTVARIABLE"))
    timevals = {k[len("TIMEVAL("):-1] for k in kw if k.startswith("TIMEVAL(")}
    fields = []
    measures = []
    for v in table["variables"]:
        texts = v["labels"].get(main, {}).get("valueTexts", v["values"])
        name_main = v["labels"].get(main, {}).get("text", v["code"])
        if contvar and contvar in (v["code"], name_main):
            measures = list(zip(v["values"], texts))
            continue
        f = Field(name=v["code"], title=name_main, type="string", role="key", minCount=1, maxCount=1)
        is_time = v["time"] or name_main in timevals or v["code"] in timevals or bool(TIME_NAMES.match(name_main))
        if is_time:
            ts_type, unit = time_kind(texts)
            f.format = unit
            if ts_type == "year" and v["values"] == texts:
                f.type = "year"
            f.stats["timeUnit"] = unit or "unknown"
            f.stats["isTime"] = True
        f.constraints["enum"] = v["values"]
        f.codeLabels = {code: {lang: v["labels"][lang]["valueTexts"][i]
                               for lang in v["labels"] if i < len(v["labels"][lang]["valueTexts"])}
                        for i, code in enumerate(v["values"])}
        f.description = "; ".join(f"{lang}: {v['labels'][lang]['text']}" for lang in v["labels"]) \
            if len(v["labels"]) > 1 else None
        f.stats.update({"distinct": len(v["values"]), "nullPercentage": 0.0})
        f.examples = [str(t) for t in texts[:3]]
        fields.append(f)

    decimals = kw.get("DECIMALS")
    numeric = "integer" if str(first(decimals) if isinstance(decimals, list) else decimals) == "0" else "number"
    units = first(kw.get("UNITS"))
    if measures:
        for code, text in measures:
            unit = first(kw.get(f'UNITS("{text}")')) or first(kw.get(f"UNITS({text})")) or units
            fields.append(Field(name=code, title=text, type=numeric, role="measure", unit=unit_iri(unit),
                                unitLabel=unit, maxCount=1))
    else:
        title = first(kw.get("CONTENTS")) or "value"
        fields.append(Field(name="value", title=title, type=numeric, role="measure", unit=unit_iri(units),
                            unitLabel=units, maxCount=1))

    cells = math.prod(len(v["values"]) for v in table["variables"])
    label = table["title"].get(main)
    return Part(label=label, rowCount=cells, cube=True, keysUnique=True, fields=fields)


def profile(path: Path, token: str, cfg, tmp: Path, detail: dict) -> list[Part]:
    table = from_pxweb(Path(path)) if token == "PXWEB" else from_px(Path(path))
    if not table["variables"]:
        raise EngineError("px-without-variables")
    return [build_part(table)]
