import json
import time

from autoprof import profile
from autoprof.config import Config


def hang(pipeline_dir, group, sniffed):
    time.sleep(60)


def test_overrunning_group_fails_with_timeout(cfg, tmp_path, monkeypatch):
    cfg = Config(tmp_path, dict(cfg.values))   # raw/ and out/ under tmp_path, not the pipeline's
    group = {"id": "g1", "dataset": "https://example.org/d", "representative": "https://example.org/x",
             "members": ["https://example.org/x"]}
    cfg.raw.mkdir(parents=True, exist_ok=True)
    (cfg.raw / "distributions.json").write_text(json.dumps({"groups": [group], "distributions": {}}))
    (cfg.raw / "sniff.json").write_text("{}")
    cfg.values["PROFILE_TIMEOUT"] = "1"
    monkeypatch.setattr(profile, "profile_group", hang)   # inherited by the forked worker
    started = time.monotonic()
    profile.run(cfg)
    assert time.monotonic() - started < 30
    d = json.loads((cfg.out / "profiles" / "g1.json").read_text())
    assert (d["status"], d["statusReason"]) == ("failed", "timeout:1s")
