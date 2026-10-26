#!/usr/bin/env bash
# Replace the <name>-latest GitHub Release assets with the validated output.
# Needs the gh CLI with a token that can write releases (GH_TOKEN in CI).
# Usage: publish.sh <name>
. "$(dirname "$0")/lib.sh"

name=${1:?usage: publish.sh <name>}
load_pipeline "$name"

tag="$NAME-latest"
ttl="$OUT/$NAME.ttl" meta="$OUT/$NAME.meta.json"
[ -s "$ttl" ] && [ -s "$meta" ] || die "nothing to publish in $OUT; run scripts/run.sh $name first"

notes="Latest $LABEL. Load into visoto with the upload modal's URL tab, graph \`$GRAPH\`.

Generated $(jq -r .generated "$meta") from commit $(jq -r .commit "$meta"), $(jq -r .triples "$meta") triples."

if gh release view "$tag" >/dev/null 2>&1; then
  gh release edit "$tag" --notes "$notes"
else
  gh release create "$tag" --title "$LABEL" --notes "$notes" --latest=false
fi
gh release upload "$tag" "$ttl" "$meta" --clobber
log "published: $(gh release view "$tag" --json url -q .url)"
