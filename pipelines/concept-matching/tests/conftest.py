import json
import shutil
import sys
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE))

from cmatch import bulk, lindas  # noqa: E402
from cmatch.config import Config  # noqa: E402

C = lindas.CONCEPT
MUNI = C + "GDE"                      # a hierarchical list: cantons (level_1) and municipalities (level_2)
SEX = C + "SEX"
AGG = C + "AGG"                       # agglomerations: codes overlap the municipality numbers partly
AGE = C + "AGE_HOURS"                 # a dense integer range
CANTONS = ["ZH", "BE", "LU", "UR", "SZ", "OW", "NW", "GL", "ZG", "FR", "SO", "BS", "BL", "SH", "AR", "AI", "SG",
           "GR", "AG", "TG", "TI", "VD", "VS", "NE", "GE", "JU"]
CANTON_NAMES = {"ZH": ("Zürich", "Zurich"), "BE": ("Bern", "Berne"), "LU": ("Luzern", "Lucerne"),
                "UR": ("Uri", "Uri"), "SZ": ("Schwyz", "Schwytz"), "OW": ("Obwalden", "Obwald"),
                "NW": ("Nidwalden", "Nidwald"), "GL": ("Glarus", "Glaris"), "ZG": ("Zug", "Zoug"),
                "FR": ("Freiburg", "Fribourg"), "SO": ("Solothurn", "Soleure"), "BS": ("Basel-Stadt", "Bâle-Ville"),
                "BL": ("Basel-Landschaft", "Bâle-Campagne"), "SH": ("Schaffhausen", "Schaffhouse"),
                "AR": ("Appenzell Ausserrhoden", "Appenzell Rhodes-Extérieures"),
                "AI": ("Appenzell Innerrhoden", "Appenzell Rhodes-Intérieures"), "SG": ("St. Gallen", "Saint-Gall"),
                "GR": ("Graubünden", "Grisons"), "AG": ("Aargau", "Argovie"), "TG": ("Thurgau", "Thurgovie"),
                "TI": ("Tessin", "Tessin"), "VD": ("Waadt", "Vaud"), "VS": ("Wallis", "Valais"),
                "NE": ("Neuenburg", "Neuchâtel"), "GE": ("Genf", "Genève"), "JU": ("Jura", "Jura")}
YESNO = [C + f"YN{i}" for i in range(1, 6)]   # the same small answer list five times: generic labels
GENERIC = [("J", "Ja"), ("N", "Nein"), ("U", "Unbekannt"), ("A", "Andere"), ("K", "Keine Angabe"),
           ("W", "Weiss nicht")]
MUNIS_2023 = [1, 2, 3, 4, 5, 261, 262, 351, 352, 371, 2196, 5586, 6621, 6622, 9999]
MUNIS_2024 = [1, 2, 3, 4, 5, 261, 262, 351, 352, 371, 2196, 5586, 6621, 6623]


def build_codes(path: Path) -> None:
    con = lindas.connect(path)
    schemes = [
        (MUNI, MUNI, "GDE", None, "Municipalities"), (MUNI + "/version/2023", MUNI, "GDE", "2023", "Municipalities 2023"),
        (MUNI + "/version/2024", MUNI, "GDE", "2024", "Municipalities 2024"),
        (SEX, SEX, "SEX", None, "Sex"), (AGG, AGG, "AGG", None, "Agglomerations"), (AGE, AGE, "AGE_HOURS", None, "Age"),
    ]
    rows = []
    for scheme, munis in ((MUNI, sorted(set(MUNIS_2023 + MUNIS_2024))), (MUNI + "/version/2023", MUNIS_2023),
                          (MUNI + "/version/2024", MUNIS_2024)):
        version = scheme.rsplit("/", 1)[-1] if "/version/" in scheme else None
        rows += [(scheme, MUNI, version, MUNI + "/level_1", c, lindas.norm(c)) for c in CANTONS]
        rows += [(scheme, MUNI, version, MUNI + "/level_2", str(n), str(n)) for n in munis]
    rows += [(SEX, SEX, None, None, c, c) for c in ("1", "2")]
    labels = []      # (scheme, list, version, level, notation, norm, kind, lang)
    for scheme in (MUNI, MUNI + "/version/2023", MUNI + "/version/2024"):
        version = scheme.rsplit("/", 1)[-1] if "/version/" in scheme else None
        for code, (de, fr) in CANTON_NAMES.items():
            labels += [(scheme, MUNI, version, MUNI + "/level_1", code, lindas.label_norm(de), "label", "de"),
                       (scheme, MUNI, version, MUNI + "/level_1", code, lindas.label_norm(fr), "label", "fr")]
    for yn in YESNO:
        schemes.append((yn, yn, yn.rsplit("/", 1)[-1], None, "Yes/no"))
        rows += [(yn, yn, None, None, c, c) for c, _ in GENERIC]
        labels += [(yn, yn, None, None, c, lindas.label_norm(l), "label", "de") for c, l in GENERIC]
    rows += [(AGG, AGG, None, None, str(n), str(n)) for n in (261, 351, 1000, 1001, 1002)]
    rows += [(AGE, AGE, None, None, str(n), str(n)) for n in range(0, 1201)]
    con.executemany("INSERT INTO schemes VALUES (?, ?, ?, ?, NULL, ?, NULL, NULL, NULL)", schemes)
    bulk.insert(con, "codes", ["scheme", "list", "version", "level", "notation", "norm"], rows)
    bulk.insert(con, "codes", ["scheme", "list", "version", "level", "notation", "norm", "kind", "lang"], labels)
    con.close()


def slot(name, sample, *, dataset="https://example.org/d1", container="main", distributions=None, datatype=None,
         type_="integer", fingerprint=None, structure="https://example.org/s1", **extra) -> dict:
    datatype = datatype or ("http://www.w3.org/2001/XMLSchema#integer" if type_ == "integer"
                            else "http://www.w3.org/2001/XMLSchema#string")
    s = {"iri": f"{structure}/{container}/{name.lower()}", "structure": structure, "engine": "tabular",
         "key": {"dataset": dataset, "distributions": distributions or [dataset + "/dist"], "container": container,
                 "sourceName": name},
         "name": name, "label": None, "description": None,
         "container": {"iri": f"{structure}/{container}", "path": container, "label": "Population", "tableName": None,
                       "slots": 3, "geometryType": None, "crs": None},
         "neighbours": [], "type": type_, "datatype": datatype, "nested": False, "unit": None, "unitLabel": None,
         "format": None, "categorical": False, "sample": [str(v) for v in sample],
         "fingerprint": fingerprint or f"fp-{name.lower()}-{structure[-2:]}"}
    s.update(extra)
    return s


@pytest.fixture
def pipeline(tmp_path) -> Config:
    """A pipeline folder with the real vocabularies and shapes, a miniature code index and no registry."""
    for name in ("pipeline.env", "shapes.ttl", "confirmations.csv"):
        shutil.copy(PIPELINE / name, tmp_path / name)
    shutil.copytree(PIPELINE / "vocab", tmp_path / "vocab")
    shutil.copytree(PIPELINE / "checks", tmp_path / "checks")
    (tmp_path / "cache").mkdir()
    build_codes(tmp_path / "cache" / "codes.duckdb")
    cfg = Config.load(tmp_path)
    cfg.values["BASE_IRI"] = "https://example.org/mds/"
    return cfg


def write_slots(cfg: Config, slots: list[dict]) -> None:
    cfg.raw.mkdir(parents=True, exist_ok=True)
    with open(cfg.raw / "slots.jsonl", "w") as f:
        for s in slots:
            f.write(json.dumps(s) + "\n")
