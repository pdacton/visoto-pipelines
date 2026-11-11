"""tune: precision and recall of the automatic code-list and identifier links on the gold set, over a
grid of code-list thresholds → out/tuning.md. Phase 4: the thresholds in pipeline.env are set from it.
Reads the current registry and slots; writes nothing else."""
import itertools
import json

from . import confirm, linkvalues, report
from . import slots as slotio
from .config import Config
from .log import log
from .registry import Registry

GRID = {"CODE_MIN_CONTAINMENT": ["0.9", "0.95", "0.98", "1.0"], "CODE_MIN_DISTINCT": ["3", "5", "6", "8", "10"],
        "CODE_MIN_LEAD": ["0.05", "0.1", "0.2"]}


def evaluate(cfg: Config, slots: list[dict], gold: list[dict]) -> dict:
    reg = Registry.load(cfg.registry_dir, cfg.base_iri)
    links = {r["slot"]: r for r in linkvalues.link(cfg, slots, reg, confirm.load(cfg))}
    return report.gold_values(gold, slots, links, reg)


def run(cfg: Config) -> None:
    slots = slotio.load(slotio.input_path(cfg))
    gold = report.read_csv(cfg.pipeline_dir / "tests" / "gold-values.csv")
    if not gold:
        raise SystemExit("tune: tests/gold-values.csv is empty")
    rows = []
    for combo in itertools.product(*GRID.values()):
        c = type(cfg)(cfg.pipeline_dir, {**cfg.values, **dict(zip(GRID, combo))})
        r = evaluate(c, slots, gold)
        rows.append([*combo, report.pct(r["precision"]), report.pct(r["recall"]), r["tp"], r["fp"], r["fn"]])
    rows.sort(key=lambda r: (-(float(r[3]) if r[3] != "–" else 0), -(float(r[4]) if r[4] != "–" else 0)))
    current = [cfg[k] for k in GRID]
    text = ["# Threshold tuning", "", f"Gold set: {len(gold)} slots. Current: {dict(zip(GRID, current))}.", "",
            report.table([*GRID, "precision", "recall", "tp", "fp", "fn"], rows)]
    (cfg.out / "tuning.md").write_text("\n".join(text) + "\n")
    log(f"tune: {len(rows)} combinations → out/tuning.md; best {dict(zip(GRID, rows[0][:3]))} "
        f"precision {rows[0][3]} recall {rows[0][4]}")
