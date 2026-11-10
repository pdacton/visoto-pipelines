#!/usr/bin/env bash
# SHACL-validate a pipeline's output and run its sanity checks.
# Usage: validate.sh <name>
. "$(dirname "$0")/lib.sh"

name=${1:?usage: validate.sh <name>}
load_pipeline "$name"
ensure_tools

ttl="$OUT/$NAME.ttl"
[ -s "$ttl" ] || die "no output: $ttl"

log "SHACL"
report="$OUT/shacl-report.ttl"
# SHAPES in pipeline.env lists shape files relative to the pipeline folder (default shapes.ttl);
# several are merged into one shapes graph. owl:imports are dropped: Jena's shacl would fetch them
# over HTTP, and a vocabulary namespace need not resolve (yet).
shapes="$OUT/shapes-merged.nt"
(cd "$PIPELINE_DIR" && riot --output=nt ${SHAPES:-shapes.ttl}) \
  | grep -v '<http://www.w3.org/2002/07/owl#imports>' > "$shapes"
shacl validate --shapes "$shapes" --data "$ttl" > "$report"
if ! grep -q 'sh:conforms *true' "$report"; then
  grep -E 'sh:resultMessage|sh:focusNode' "$report" | head -40 >&2
  die "SHACL validation failed, see $report"
fi

# Per-pipeline checks: checks/*.rq are SELECT queries returning a ?problem
# row for each failure; any row fails the run.
if [ -d "$PIPELINE_DIR/checks" ]; then
  for q in "$PIPELINE_DIR"/checks/*.rq; do
    problems=$(arq --data "$ttl" --query "$q" --results=TSV | tail -n +2)
    [ -z "$problems" ] || die "check $(basename "$q") failed: $problems"
  done
fi

log "valid: $(grep -c '' "$ttl") lines of Turtle"
