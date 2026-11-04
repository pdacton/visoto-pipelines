"""report: out/report.md — counts, format mismatches, slowest distributions, failures."""
import json
from collections import Counter

from .config import Config
from .log import log


def table(headers: list[str], rows: list[list]) -> str:
    def cell(v):
        return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    return "\n".join(lines)


def run(cfg: Config) -> None:
    sniffed = json.loads((cfg.raw / "sniff.json").read_text())
    resolve = json.loads((cfg.raw / "resolve-report.json").read_text())
    profiles = {p.stem: json.loads(p.read_text()) for p in (cfg.out / "profiles").glob("*.json")
                if not p.name.startswith("_")}
    run_info = json.loads((cfg.out / "profiles" / "_run.json").read_text())

    status = Counter(p["status"] for p in profiles.values())
    by_engine = Counter((p.get("engine") or "-", p["status"]) for p in profiles.values())
    reasons = Counter((p["status"], (p.get("statusReason") or "").split(":")[0] + (
        ":" + p["statusReason"].split(":")[1] if (p.get("statusReason") or "").startswith("out-of-scope") else ""))
        for p in profiles.values() if p["status"] != "profiled")
    out = [f"# auto-profiling report", "",
           f"Run `{run_info['id']}`, {run_info['started'][:19]} to {run_info['ended'][:19]} UTC, "
           f"SAMPLE_ROWS {run_info['sampleRows']}.", "",
           table(["", "count"], [["datasets", resolve["datasets"]],
                                 ["unknown datasets", len(resolve["unknown"])],
                                 ["datasets without distributions", len(resolve["withoutDistributions"])],
                                 ["distributions", resolve["distributions"]],
                                 ["structures (equivalence groups)", len(profiles)]]
                 + [[f"structures {k}", v] for k, v in sorted(status.items())]
                 + [["parts", sum(len(p.get("parts", [])) for p in profiles.values())],
                    ["fields", sum(len(pt.get("fields", [])) for p in profiles.values() for pt in p.get("parts", []))],
                    ["cube:Constraint parts", sum(1 for p in profiles.values() for pt in p.get("parts", [])
                                                  if _cube(pt))]]),
           "", "## Per engine", "",
           table(["engine", "status", "structures"], [[e, s, n] for (e, s), n in sorted(by_engine.items())]),
           "", "## Skip and failure reasons", "",
           table(["status", "reason", "structures"],
                 [[s, r, n] for (s, r), n in sorted(reasons.items(), key=lambda x: -x[1])])]

    mismatches = [[gid, "\\|".join(r.get("declared", [])), r.get("sniffed"), (r.get("detail") or {}).get("inner"),
                   r.get("url")] for gid, r in sniffed.items() if r.get("match") is False]
    out += ["", "## Declared versus sniffed format", "",
            f"{len(mismatches)} representatives whose content disagrees with their metadata.", ""]
    if mismatches:
        out.append(table(["structure", "declared", "sniffed", "inner", "URL"], mismatches))

    slow = sorted(((r.get("seconds", 0) + (profiles.get(gid, {}).get("seconds") or 0), gid, r)
                   for gid, r in sniffed.items()), key=lambda x: -x[0])[:20]
    out += ["", "## Slowest 20", "",
            table(["structure", "fetch s", "profile s", "status", "bytes", "URL"],
                  [[gid, r.get("seconds"), profiles.get(gid, {}).get("seconds"),
                    profiles.get(gid, {}).get("status"), r.get("bytes"), r.get("url")] for _, gid, r in slow])]

    failures = sorted((p for p in profiles.values() if p["status"] == "failed"), key=lambda p: p["statusReason"] or "")
    out += ["", "## Failures", "",
            table(["structure", "dataset", "reason", "URL"],
                  [[p["id"], p["dataset"].rsplit("/", 1)[-1], p.get("statusReason"), p.get("url")]
                   for p in failures]) if failures else "None."]
    if resolve["unknown"] or resolve["withoutDistributions"]:
        out += ["", "## Datasets not resolved", ""]
        out += [f"- unknown: {d}" for d in resolve["unknown"]]
        out += [f"- no distributions: {d}" for d in resolve["withoutDistributions"]]
    (cfg.out / "report.md").write_text("\n".join(out) + "\n")
    log(f"report: out/report.md ({dict(status)})")


def _cube(part: dict) -> bool:
    from .model import _part
    return _part(part).is_cube()
