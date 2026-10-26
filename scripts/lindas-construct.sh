#!/usr/bin/env bash
# Run a CONSTRUCT query file against a SPARQL endpoint, write N-Triples.
# Usage: lindas-construct.sh <endpoint> <query-file> <out.nt>
. "$(dirname "$0")/lib.sh"

endpoint=$1 query=$2 out=$3
fetch -X POST "$endpoint" \
  -H 'Accept: application/n-triples' \
  --data-urlencode "query@$query" \
  -o "$out.part"
mv "$out.part" "$out"
