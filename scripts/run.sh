#!/usr/bin/env bash
# fetch → transform → validate for one pipeline; result in pipelines/<name>/out/.
# Usage: run.sh <name> [--skip-fetch]
. "$(dirname "$0")/lib.sh"

name=${1:?usage: run.sh <name> [--skip-fetch]}
load_pipeline "$name"
ensure_tools

if [ "${2:-}" != "--skip-fetch" ]; then
  log "fetch"
  rm -rf "$RAW"; mkdir -p "$RAW"
  (cd "$PIPELINE_DIR" && ./fetch.sh)
fi

log "transform"
rm -rf "$OUT"; mkdir -p "$OUT/parts"
cd "$PIPELINE_DIR"   # queries use locations relative to the pipeline folder
for q in queries/*.sparql; do
  part="$OUT/parts/$(basename "$q" .sparql).nt"
  sa "$q" "$part"
  log "  $(basename "$q"): $(wc -l < "$part") triples"
done

log "merge"
# Mapped parts plus the raw files the pipeline copies unchanged (COPY in
# pipeline.env). riot scopes blank node labels per input file, so they can't collide.
riot --formatted=TTL "$OUT"/parts/*.nt $COPY > "$OUT/$NAME.ttl"

"$ROOT/scripts/validate.sh" "$name"
"$ROOT/scripts/meta.sh" "$name"
