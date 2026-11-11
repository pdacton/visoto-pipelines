#!/usr/bin/env bash
# Transform: registry → confirm → link-values → link-concepts → emit → report.
# scripts/run.sh runs this, then merges out/parts/*.nt into out/concept-matching.ttl.
. "$(dirname "$0")/../../scripts/lib.sh"
cd "$(dirname "$0")"
ensure_uv
uv run --quiet python -m cmatch registry
uv run --quiet python -m cmatch confirm
uv run --quiet python -m cmatch link-values
uv run --quiet python -m cmatch link-concepts
uv run --quiet python -m cmatch emit
uv run --quiet python -m cmatch report
