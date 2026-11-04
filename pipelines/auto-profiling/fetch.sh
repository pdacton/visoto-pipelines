#!/usr/bin/env bash
# Extract: datasets.txt → raw/distributions.json (SPARQL), raw/samples/* and raw/sniff.json (HTTP).
# Samples are cached in cache/ by ETag/Last-Modified, which survives run.sh wiping raw/.
. "$(dirname "$0")/../../scripts/lib.sh"
cd "$(dirname "$0")"
ensure_uv
uv run --quiet python -m autoprof resolve
uv run --quiet python -m autoprof fetch
