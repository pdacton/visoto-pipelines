#!/usr/bin/env bash
# Extract: I14Y API → raw/api/*.json and raw/catalogs/*.ttl, LINDAS → raw/lindas/*.nt
. "$(dirname "$0")/../../scripts/lib.sh"
load_pipeline i14y
ensure_tools
mkdir -p "$RAW/api" "$RAW/catalogs" "$RAW/lindas" "$RAW/tmp"

# --- I14Y API -------------------------------------------------------------

# All pages of a collection, merged into one JSON array: raw/api/<c>.json
fetch_collection() {
  local c=$1 page=1
  while :; do
    fetch "$I14Y_API/$c?pageSize=1000&page=$page" -o "$RAW/tmp/$c-$page.json"
    [ "$(jq '.data | length' "$RAW/tmp/$c-$page.json")" -gt 0 ] || break
    page=$((page + 1))
  done
  jq -s '[.[].data[]]' "$RAW/tmp/$c"-*.json > "$RAW/api/$c.json"
  log "  $c: $(jq length "$RAW/api/$c.json")"
}

log "I14Y API"
for c in dataservices publicservices catalogs; do fetch_collection "$c"; done

# Catalogs come as DCAT Turtle from I14Y itself; no mapping needed.
jq -r '.[].id' "$RAW/api/catalogs.json" |
  xargs -P 8 -I{} curl -fsSL --retry 4 --retry-all-errors \
    -o "$RAW/catalogs/{}.ttl" "$I14Y_API/catalogs/{}/dcat/exports/ttl"
log "  catalog exports: $(ls "$RAW/catalogs" | wc -l)"
# One file for SPARQL Anything; riot resolves each export's @base and keeps
# their blank nodes apart.
riot --output=NT "$RAW"/catalogs/*.ttl > "$RAW/api/catalogs.nt"

# Data services and public services point to datasets by internal id, but
# dataset IRIs use the dataset's identifier. Look those up: raw/api/dataset-ids.json
jq -r '.[].servesDatasets[]?.id' "$RAW/api/dataservices.json" > "$RAW/tmp/dataset-ids.txt"
jq -r '.[].isDescribedAt[]?.id' "$RAW/api/publicservices.json" >> "$RAW/tmp/dataset-ids.txt"
sort -u "$RAW/tmp/dataset-ids.txt" | while read -r id; do
  # Non-public datasets return 404; their links are dropped.
  curl -fsSL --retry 4 "$I14Y_API/datasets/$id" 2>/dev/null |
    jq -c '(.data // .) | {id, identifier: .identifiers[0]}' || true
done | jq -s . > "$RAW/api/dataset-ids.json"
log "  referenced datasets: $(jq length "$RAW/api/dataset-ids.json")"

# --- LINDAS ---------------------------------------------------------------

log "LINDAS"
fetch -X POST "$LINDAS_ENDPOINT" -H 'Accept: text/csv' \
  --data-urlencode "query@lindas/dataset-list.sparql" |
  tail -n +2 | tr -d '\r' | sort > "$RAW/tmp/datasets.txt"
log "  datasets: $(wc -l < "$RAW/tmp/datasets.txt")"

split -l "$LINDAS_BATCH" -d -a 3 "$RAW/tmp/datasets.txt" "$RAW/tmp/batch-"
for b in "$RAW"/tmp/batch-*; do
  values=$(sed 's/.*/<&>/' "$b" | tr '\n' ' ')
  sed "s|#VALUES#|$values|" lindas/datasets.sparql > "$b.sparql"
  "$ROOT/scripts/lindas-construct.sh" "$LINDAS_ENDPOINT" "$b.sparql" "$RAW/lindas/datasets-${b##*-}.nt"
done
"$ROOT/scripts/lindas-construct.sh" "$LINDAS_ENDPOINT" lindas/concept-schemes.sparql "$RAW/lindas/concept-schemes.nt"
log "  triples: $(cat "$RAW"/lindas/*.nt | wc -l)"

rm -rf "$RAW/tmp"
