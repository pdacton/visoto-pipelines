import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfg(tmp_path):
    from autoprof.config import Config
    c = Config.load()
    c.values["SAMPLE_ROWS"] = "10000"
    return c
