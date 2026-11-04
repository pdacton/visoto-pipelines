#!/usr/bin/env bash
# Transform: raw/samples/* → out/profiles/*.json → out/parts/*.nt, plus out/report.md.
# scripts/run.sh runs this instead of the queries/*.sparql loop, then merges out/parts/*.nt.
. "$(dirname "$0")/../../scripts/lib.sh"
cd "$(dirname "$0")"
ensure_uv
uv run --quiet python -m autoprof profile
uv run --quiet python -m autoprof emit
uv run --quiet python -m autoprof report
