# Transform: SPARQL Anything

Status: **decided**.

## Why

- Mappings are declarative SPARQL `CONSTRUCT` queries over JSON (Facade-X),
  one per resource type — reviewable without reading code.
- Handles blank nodes and other SPARQL features natively; mature and well
  tested.
- The whole pipeline stays in SPARQL: LINDAS `CONSTRUCT` queries, JSON
  mappings, SHACL validation.
- Single jar (version pinned); runs on a stock Actions runner with
  `actions/setup-java`.
- The JSON part is small (data services, public services, catalogs — a few
  hundred records).

## Division of labour

SPARQL Anything does not paginate an API. So:

- **fetch** (`curl` loop) pages through the API collections not on LINDAS
  (data services, public services, catalogs) and writes
  `raw/<collection>/page-N.json`; it also runs the `lindas/*.sparql`
  `CONSTRUCT` queries, paged by dataset, into `raw/lindas/*.ttl`;
- **transform** runs SPARQL Anything over the JSON files only. The LINDAS
  Turtle is already RDF and is merged into the output unchanged.

This also keeps the transform reproducible offline from a saved `raw/`.

## Mapping rules

- Main resources get their I14Y IRIs (see [02-i14y-source.md](02-i14y-source.md));
  blank nodes only for nested structures such as contact points, since they
  get a new identity on every run.
- Multilingual `{de, en, fr, it}` objects become `"..."@de` etc.
- The SHACL shapes cover the API-derived output. The LINDAS copy is not
  reshaped; validation only checks it is non-empty and its dataset count is
  close to the previous run, so an upstream outage can't publish an empty graph.
