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
3. Replace the graph, don't add to it: observed statistics and the run IRI
   change with every run, and IRIs change when a structure's representative
   distribution changes, so adding would keep stale structures. The upload
   modal **appends** (Graph Store POST, verified 2026-11-10). To replace,
   delete the graph first (visoto's named-graph list, `DELETE
   /api/named-graphs`) and then upload, or send a Graph Store **PUT**, which
   QLever supports and which replaces only the named graph. Either way only
   that one graph changes; the concept-matching confirmations graph is never
   touched.
4. Check the load, e.g. with the visoto MCP `run_sparql_query` on
   `visoto-qlever`:

   ```sparql
   PREFIX ap: <https://register.ld.admin.ch/mds/ontology/ap/>
   SELECT ?class (COUNT(?s) AS ?n) WHERE {
     GRAPH <urn:data:auto-profiling-githubpipeline> { ?s a ?class }
     VALUES ?class { ap:DataStructure ap:Container ap:Slot ap:Observation
                     <http://w3id.org/rml/LogicalSource> <https://cube.link/Constraint> }
   } GROUP BY ?class
   ```

   and compare with the `classes` counts in `out/auto-profiling.meta.json`.

Verified 2026-11-10 on a local visoto-qlever with the 500-dataset run
(1,109,366 triples, 84 MB Turtle): loaded in 16 s, class counts equal to
`meta.json`, three structures (tabular, geo, PX) spot-checked. The load grew
QLever's memory by about 510 MiB: uploaded triples are kept as delta triples
in memory, about 460 bytes each.

### Size

| Run | Distributions | Triples | Turtle | slots.jsonl |
|---|---|---|---|---|
| 500 datasets (2026-11-10) | 3,293 | 1.11M | 84 MB | 61 MB |
| all of ODS (extrapolated) | ~35,500 | ~12M | ~900 MB | ~660 MB |

A full run does not fit the current import path: the file exceeds the upload
modal's `max_upload_mb` (200), and as delta triples it would take about
5.5 GB of visoto-qlever's memory. Before a full run, decide between loading it
into the QLever index (rebuild, as the bootstrap index is built) and splitting
it into several graphs.

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
- Linking values to LINDAS shared dimensions or I14Y concepts: done in the
  separate [concept-matching](../concept-matching/) pipeline.

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
emit     → out/parts/*.nt → out/auto-profiling.ttl      (SHACL + ap:), out/slots.jsonl
validate → shapes.ttl + vocab/ap-shapes.ttl, checks/*.rq (validate.sh)
```

`resolve` and `fetch` belong to `fetch.sh`; `profile` and `emit` belong to
`transform.sh`. So `scripts/run.sh auto-profiling --skip-fetch` re-profiles
offline from saved samples.
