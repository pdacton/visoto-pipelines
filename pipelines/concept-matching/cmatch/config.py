"""Pipeline settings from pipeline.env, overridable through the environment."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "NAME": "concept-matching",
    "GRAPH": "urn:data:concept-matching-githubpipeline",
    "CONFIRMATIONS_GRAPH": "urn:data:concept-matching-confirmations",
    "BASE_IRI": "https://register.ld.admin.ch/mds/",
    "SLOTS": "../auto-profiling/out/slots.jsonl",
    "LINDAS_ENDPOINT": "https://ld.admin.ch/query",
    "I14Y_GRAPH": "https://lindas.admin.ch/fso/i14y",
    "CODE_MIN_CONTAINMENT": "0.98",
    "CODE_MIN_DISTINCT": "6",
    "CODE_MIN_LEAD": "0.1",
    "CODE_CANDIDATE_MIN": "0.5",
    "CANDIDATES": "3",
    "ID_MIN_RATE": "0.95",
    "CONCEPT_MODEL": "none",
    "CONCEPT_MIN_CONFIDENCE": "0.8",
    "NEAREST": "8",
    "SHAPES": "shapes.ttl",
}


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines as written for `. pipeline.env`; quotes stripped, ${VAR:-default} expanded."""
    values = {}
    for line in path.read_text().splitlines():
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if not m or line.lstrip().startswith("#"):
            continue
        v = m.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        if d := re.fullmatch(r"\$\{([A-Z_][A-Z0-9_]*):-(.*)\}", v):
            v = os.environ.get(d.group(1)) or d.group(2)
        values[m.group(1)] = v
    return values


@dataclass
class Config:
    pipeline_dir: Path = PIPELINE_DIR
    values: dict = field(default_factory=dict)

    @classmethod
    def load(cls, pipeline_dir: Path = PIPELINE_DIR) -> "Config":
        values = dict(DEFAULTS)
        env_file = pipeline_dir / "pipeline.env"
        if env_file.exists():
            values.update(read_env_file(env_file))
        # Only values written as ${VAR:-default} in pipeline.env follow the environment (read_env_file):
        # a blanket override would let e.g. the shell's NAME (the host name) replace the pipeline's.
        return cls(pipeline_dir, values)

    def __getitem__(self, key: str) -> str:
        return self.values[key]

    def int(self, key: str) -> int:
        return int(self.values[key])

    def float(self, key: str) -> float:
        return float(self.values[key])

    @property
    def base_iri(self) -> str:
        b = self.values["BASE_IRI"]
        return b if b.endswith(("/", "#")) else b + "/"

    @property
    def raw(self) -> Path:
        return self.pipeline_dir / "raw"

    @property
    def out(self) -> Path:
        return self.pipeline_dir / "out"

    @property
    def cache(self) -> Path:
        # Outside raw/: scripts/run.sh wipes raw/ before every fetch.
        return self.pipeline_dir / "cache"

    @property
    def registry_dir(self) -> Path:
        return self.pipeline_dir / "registry"

    @property
    def codes_db(self) -> Path:
        return self.cache / "codes.duckdb"
