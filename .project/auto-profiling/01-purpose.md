# Purpose

Auto-detect the data structure of opendata.swiss distributions and publish it
as SHACL, so visoto can show field names, types, code lists and value
distributions next to each dataset.

Status: **implemented** (2026-11-03); see [03-plan.md](03-plan.md).

## Input

`pipelines/auto-profiling/datasets.txt`: one opendata.swiss dataset IRI per
line (`#` comments and blank lines ignored), e.g.

```
https://opendata.swiss/set/data/00_01_liste_menages_collectifs_lhr-ssd
```

The pipeline resolves each dataset's distributions itself, from the ODS ABN
endpoint (`https://trifid.abn.ods.zazukoians.org/query`).

## Output

One Turtle file, `pipelines/auto-profiling/out/auto-profiling.ttl`, for the
named graph `urn:data:auto-profiling-githubpipeline`. It is imported by hand
through visoto's upload modal into the `visoto-qlever` endpoint
(<https://visoto.hutzli.org/?endpoint=visoto-qlever>). `scripts/publish.sh`
works as well, but is not required.

Adapting visoto's templates to show the structures is **out of scope**; it is
done in a separate session once the triples are loaded.

### Import into visoto

1. `scripts/run.sh auto-profiling` (or `--skip-fetch` to re-profile from the
   saved samples); the run validates `out/auto-profiling.ttl` and writes
   `out/report.md`.
2. Open <https://visoto.hutzli.org/?endpoint=visoto-qlever>, open the upload
   modal, choose the file `pipelines/auto-profiling/out/auto-profiling.ttl`
   and the named graph `urn:data:auto-profiling-githubpipeline`.
3. Replace the graph on load rather than adding to it: IRIs are stable across
   runs, but observed statistics and the run IRI change, so adding would keep
   stale profiles. (Whether the modal replaces or appends is the same open
   question as for the i14y pipeline.)
4. Check the load, e.g. with the visoto MCP `run_sparql_query` on
   `visoto-qlever`:

   ```sparql
   SELECT ?class (COUNT(?s) AS ?n) WHERE {
     GRAPH <urn:data:auto-profiling-githubpipeline> { ?s a ?class }
     VALUES ?class { <https://example.org/auto-profiling/prof#Structure>
                     <http://www.w3.org/ns/shacl#PropertyShape> <https://cube.link/Constraint> }
   } GROUP BY ?class
   ```

   and compare with the `classes` counts in `out/auto-profiling.meta.json`.

## Scope

Formats, chosen from the format analysis of 2026-11-03 (about 35,500
distributions on ODS):

| Family | Formats | Engine |
|---|---|---|
| Tabular | CSV, XLSX, XLS, ODS, Parquet, tabular JSON | DuckDB + Frictionless |
| Geo | SHP (in ZIP), GPKG, GML, WFS | DuckDB `spatial` (GDAL) |
| Statistical cube | PX (PC-Axis, PxWeb) | pyaxis |
| Tree | JSON, XML | genson / XSD / path statistics |
| Graph | JSON-LD, Turtle, N3, RDF/XML | sheXer |

Out of scope for now:
- HTML, PDF, WMS/WMTS, images, code and documents.
- GeoJSON. JSON distributions that turn out to be GeoJSON are recorded as
  skipped.
- Linking values to LINDAS shared dimensions or I14Y concepts.

## Runs on

The developer's machine, which needs unrestricted outbound HTTP to the data
portals. It is not run in CI yet. The pipeline queries SPARQL endpoints over
plain HTTP; the visoto MCP server is a development aid for Claude Code
(checking queries, inspecting ODS, verifying the import), not a runtime
dependency.

## How it fits the repo

Same shape as `i14y`: `pipelines/auto-profiling/` with `pipeline.env`, a
`fetch.sh`, `shapes.ttl` and `checks/*.rq`, run by `scripts/run.sh`. The
difference is the transform: Python (DuckDB, Frictionless and friends)
instead of SPARQL Anything. A `transform.sh` hook in `scripts/run.sh` makes
that possible without touching the i14y pipeline.

Stages, each rerunnable from the files of the previous one:

```
resolve  datasets.txt → raw/distributions.json         (SPARQL)
fetch    → raw/samples/*, raw/sniff.json                (HTTP, sniffing)
profile  → out/profiles/*.json                          (format engines)
emit     → out/parts/*.nt → out/auto-profiling.ttl      (SHACL + prof:)
validate → shapes.ttl, checks/*.rq                      (existing validate.sh)
```

`resolve` and `fetch` belong to `fetch.sh`; `profile` and `emit` belong to
`transform.sh`. So `scripts/run.sh auto-profiling --skip-fetch` re-profiles
offline from saved samples.
