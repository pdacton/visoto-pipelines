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
- The JSON part is small (data services, public services — a few hundred
  records); the whole transform runs in about 10 s.

## Division of labour

SPARQL Anything does not paginate an API. So:

- **fetch** pages through the API collections into `raw/api/<collection>.json`,
  downloads the catalog exports (merged into `raw/api/catalogs.nt`), and runs
  the `lindas/*.sparql` `CONSTRUCT` queries, 250 datasets per request, into
  `raw/lindas/*.nt`;
- **transform** runs `queries/*.sparql` with SPARQL Anything: data services
  and public services from JSON, catalog records from the export;
- **merge** combines the mapped parts with `raw/lindas/*.nt` unchanged.

This also keeps the transform reproducible offline from a saved `raw/`
(`scripts/run.sh i14y --skip-fetch`).

## Mapping rules

- Main resources get their I14Y IRIs (see [02-i14y-source.md](02-i14y-source.md));
  blank nodes only for nested structures such as contact points, since they
  get a new identity on every run.
- Multilingual `{de, en, fr, it}` objects become `"..."@de` etc.
- The SHACL shapes cover the API-derived output. The LINDAS copy is not
  reshaped; `checks/counts.rq` sets a minimum count per main class, so a
  partial upstream response can't publish a near-empty graph.
