#!/usr/bin/env bash
# Extract: the I14Y code index from LINDAS → cache/codes.duckdb (kept across runs; refreshed when
# LINDAS has other schemes), and the slots of the last auto-profiling run → raw/slots.jsonl.
. "$(dirname "$0")/../../scripts/lib.sh"
cd "$(dirname "$0")"
ensure_uv
uv run --quiet python -m cmatch codes
uv run --quiet python -m cmatch slots
