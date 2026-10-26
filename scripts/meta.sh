#!/usr/bin/env bash
# Write out/<name>.meta.json describing a validated output.
# Usage: meta.sh <name>
. "$(dirname "$0")/lib.sh"

name=${1:?usage: meta.sh <name>}
load_pipeline "$name"
ensure_tools

ttl="$OUT/$NAME.ttl"
triples=$(riot --count "$ttl" 2>&1 | grep -oE 'Triples = [0-9,]+' | tr -dc 0-9)
classes=$(arq --data "$ttl" --results=TSV \
    'SELECT ?class (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s a ?class } GROUP BY ?class ORDER BY DESC(?n)' |
  tail -n +2 | jq -R 'split("\t") | {(.[0] | ltrimstr("<") | rtrimstr(">")): (.[1] | tonumber)}' | jq -s 'add')
jq -n \
  --arg name "$NAME" --arg graph "$GRAPH" --arg label "$LABEL" \
  --arg generated "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg commit "$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)" \
  --argjson triples "$triples" --argjson classes "$classes" \
  '{name: $name, graph: $graph, label: $label, generated: $generated, commit: $commit, triples: $triples, classes: $classes}' \
  > "$OUT/$NAME.meta.json"
log "meta: $triples triples"
