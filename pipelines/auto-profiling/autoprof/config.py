"""Pipeline settings from pipeline.env, overridable through the environment."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "NAME": "auto-profiling",
    "GRAPH": "urn:data:auto-profiling-githubpipeline",
    "ODS_ENDPOINT": "https://trifid.abn.ods.zazukoians.org/query",
    "BASE_IRI": "https://example.org/auto-profiling/",
    "SAMPLE_ROWS": "10000",
    "MAX_DOWNLOAD_MB": "50",
    "CONCURRENCY": "8",
    "PER_HOST": "2",
    "HTTP_TIMEOUT": "30",
    "DATASETS": "datasets.txt",
    "WFS_MAX_LAYERS": "20",
    "WFS_FEATURES": "1000",
    "FETCH_DEADLINE": "300",
    "PROFILE_TIMEOUT": "300",
}


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines as written for `. pipeline.env`; quotes stripped, no expansion."""
    values = {}
    for line in path.read_text().splitlines():
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if not m or line.lstrip().startswith("#"):
            continue
        v = m.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        if d := re.fullmatch(r"\$\{([A-Z_][A-Z0-9_]*):-(.*)\}", v):   # ${VAR:-default}, as the shell reads it
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
        values.update({k: os.environ[k] for k in values if k in os.environ})
        return cls(pipeline_dir, values)

    def __getitem__(self, key: str) -> str:
        return self.values[key]

    def int(self, key: str) -> int:
        return int(self.values[key])

    @property
    def base_iri(self) -> str:
        b = self.values["BASE_IRI"]
        return b if b.endswith(("/", "#")) else b + "/"

    @property
    def max_bytes(self) -> int:
        return self.int("MAX_DOWNLOAD_MB") * 1024 * 1024

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
