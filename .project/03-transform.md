# Transform: SPARQL Anything

Status: **under evaluation** — chosen as the first candidate, to be confirmed
on the I14Y pipeline.

## Why

- Mappings are declarative SPARQL `CONSTRUCT` queries over JSON (Facade-X),
  one per resource type — reviewable without reading code.
- Single jar; runs on a stock Actions runner with `actions/setup-java`.
- I14Y volume (a few thousand records) is well within its limits.

## Division of labour

SPARQL Anything does not paginate an API. So:

- **fetch** (`curl` loop) pages through each collection and writes
  `raw/<collection>/page-N.json`, plus one file per code-list concept;
- **transform** runs SPARQL Anything over those local files.

This also keeps the transform reproducible offline from a saved `raw/`.

## Evaluation criteria

- Multilingual objects map cleanly to `"..."@de` etc.
- Nested arrays (contact points, distributions, themes) need no workarounds.
- Run time and memory for the full I14Y set on a GitHub runner.
- Output passes the SHACL shapes.

If it fails these, fall back to a small Python transform (rdflib).
