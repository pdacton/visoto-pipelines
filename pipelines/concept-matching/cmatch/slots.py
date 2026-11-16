"""slots: the auto-profiling output this pipeline reads → raw/slots.jsonl and raw/containers.jsonl (snapshots)."""
import json
import shutil
from collections import defaultdict
from pathlib import Path

from .config import Config
from .log import log


def load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def by_fingerprint(slots: list[dict]) -> dict[str, list[dict]]:
    """Slots grouped by fingerprint: matching runs once per group, the result applies to each slot."""
    groups = defaultdict(list)
    for s in slots:
        groups[s["fingerprint"]].append(s)
    return dict(groups)


def key_of(slot: dict) -> tuple:
    """The re-attach key without its distributions (matched by overlap, not equality)."""
    k = slot["key"]
    return k["dataset"], k["container"], k["sourceName"]


def input_path(cfg: Config) -> Path:
    return cfg.raw / "slots.jsonl"


def containers_path(cfg: Config) -> Path:
    return cfg.raw / "containers.jsonl"


def load_containers(cfg: Config) -> dict[str, dict]:
    """container IRI → auto-profiling's container record (whole table, dataset context, dependencies);
    empty when the snapshot has none (auto-profiling output from before phase 3b)."""
    path = containers_path(cfg)
    return {c["iri"]: c for c in load(path)} if path.exists() else {}


def run(cfg: Config) -> None:
    src = (cfg.pipeline_dir / cfg["SLOTS"]).resolve()
    if not src.exists():
        raise SystemExit(f"slots: {src} not found; run the auto-profiling pipeline first")
    cfg.raw.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, input_path(cfg))
    csrc = (cfg.pipeline_dir / cfg["CONTAINERS"]).resolve()
    if csrc.exists():
        shutil.copyfile(csrc, containers_path(cfg))
    else:
        containers_path(cfg).unlink(missing_ok=True)
        log(f"slots: WARNING {csrc} not found; the concept step sees no dataset context or dependencies")
    slots = load(input_path(cfg))
    log(f"slots: {len(slots)} slots, {len(by_fingerprint(slots))} fingerprints, "
        f"{len(load_containers(cfg))} containers from {src.parent}")
