# Implementation plan

Status: phases 0–9 implemented on one branch and PR (2026-11-03), except
verifying a manual import in visoto-qlever. Deviations from this plan are
listed under [Implementation notes](#implementation-notes-2026-11-03).

The pipeline is built in phases. Each phase ends in a working
`scripts/run.sh auto-profiling` and was planned as its own PR. Phases 0–4 give a usable
pipeline for tabular data. Phases 5–8 add one format family each and are
independent of each other.

Conventions for every phase:

- **Python:** 3.12, managed with `uv` (`pipelines/auto-profiling/pyproject.toml`
  and `uv.lock`).
- **Pinned versions:** `duckdb==2.0.*` (relations have no `fetchone()`, use
  `fetchall()`), `frictionless[excel,ods,parquet]==5.21.*`, `rdflib`,
  `httpx`, `python-magic`.
- **Tests:** `pytest` with offline fixtures in `tests/fixtures/`; no network in
  tests.
- **Code layout:** `pipelines/auto-profiling/autoprof/`, one module per stage
  and one per engine.
- **Logging:** through `scripts/lib.sh` `log` style
  (`[HH:MM:SS] message` on stderr).
- **Tool use:** Claude Code may use the visoto MCP server (`run_sparql_query`
  on `opendata.next ABN` and `visoto-qlever`) to check queries and verify
  results, but the pipeline itself only uses HTTP.

## Phase 0: Scaffold

Goal: an empty pipeline that runs end to end and validates.

- [x] `pipelines/auto-profiling/` with:
  - `pipeline.env`: `NAME=auto-profiling`,
    `GRAPH=urn:data:auto-profiling-githubpipeline`, `LABEL`,
    `ODS_ENDPOINT=https://trifid.abn.ods.zazukoians.org/query`,
    `BASE_IRI=https://example.org/auto-profiling/`, `SAMPLE_ROWS=10000`,
    `MAX_DOWNLOAD_MB=50`, `CONCURRENCY=8`, `PER_HOST=2`, `HTTP_TIMEOUT=30`,
    `DATASETS=datasets.txt`.
  - `datasets.txt`: about 10 test datasets, with at least one each of CSV,
    XLSX, Parquet, SHP, GPKG, WFS, PX, XML, JSON and RDF. Pick them with the
    visoto MCP on `opendata.next ABN`.
  - `fetch.sh` and `transform.sh`: thin wrappers calling
    `uv run python -m autoprof <stage>`.
  - `pyproject.toml`, `autoprof/__main__.py` with subcommands `resolve`,
    `fetch`, `profile`, `emit`.
  - `vocab/prof.ttl`, `shapes.ttl` (shapes for the output itself),
    `checks/` (empty).
- [x] `scripts/run.sh`: if `$PIPELINE_DIR/transform.sh` exists, run it instead
  of the `queries/*.sparql` loop, then merge `out/parts/*.nt`. The `i14y`
  pipeline must behave exactly as before.
- [x] Root `README.md`: add the pipeline to the table and note the Python/uv
  requirement.

Done when `scripts/run.sh auto-profiling` produces a valid (near-empty)
`out/auto-profiling.ttl` and `scripts/run.sh i14y --skip-fetch` still passes.

## Phase 1: Resolve distributions

Goal: dataset IRIs → `raw/distributions.json`.

- [x] SPARQL against `ODS_ENDPOINT`, in batches of 100 datasets with
  `VALUES ?dataset { … }`. Return dataset, distribution, `downloadURL`,
  `accessURL`, `dct:format`, `dcat:mediaType`, `dct:title`, `dct:modified` and
  `dct:identifier`. The base is the selection query from 2026-11-03.
- [x] Compute the declared types from format, media type and URL extension
  (the mapping table in `autoprof/formats.py`). Keep conflicts as a list, for
  example `["PX","JSON"]`.
- [x] Group equivalent distributions per dataset (same publisher export, see
  [02-model.md](02-model.md)) and mark one representative per group.
- [x] Record unknown dataset IRIs and datasets without distributions in
  `raw/resolve-report.json`.

Done when the test datasets resolve and the per-type counts match the visoto
MCP query; a unit test covers the type mapping (`PX|JSON` and `CSV|XLS`
cases).

## Phase 2: Fetch and sniff

Goal: a small, reusable sample per representative distribution, plus its
sniffed format.

- [x] Async `httpx` client:
  - `CONCURRENCY` overall, `PER_HOST` per host, retries with backoff.
  - User-Agent `visoto-pipelines/auto-profiling`.
- [x] `HEAD` request, then a ranged `GET` of the first 64 KB. Sniff the bytes
  with libmagic plus the content rules (Parquet `PAR1`, GPKG application_id,
  first ZIP entry, OLE2, PX keywords, `@context`/`FeatureCollection`, XML
  root namespace, Turtle prefixes, `csv.Sniffer`, HTML rejection).
- [x] Sample by format:
  - **Parquet:** the footer via a tail range request; download in full if
    under `MAX_DOWNLOAD_MB`.
  - **ZIP:** read the central directory from the tail; fetch the whole file
    only if it holds SHP, GPKG or CSV and is under the limit.
  - **CSV and text formats:** stream until `SAMPLE_ROWS` lines or the size
    limit.
  - **WFS:** `GetCapabilities`, `DescribeFeatureType`, and
    `GetFeature&count=SAMPLE_ROWS`.
  - **XLS, XLSX, ODS, GPKG:** in full if under the limit, otherwise
    `skipped(too-large)`.
- [x] Store the samples as `raw/samples/{id}.{ext}`.
- [x] Write `raw/sniff.json` with, per distribution: declared, sniffed,
  match, HTTP status, bytes, sample path, and a status of `ok`, `skipped` or
  `failed` with a reason.
- [x] Cache by URL plus ETag or Last-Modified in `raw/cache.json`, so a rerun
  only refetches what changed.

Done when every test dataset ends with a sniffed format or an explicit
skip or failure reason. HTML error pages and login walls must be detected,
and sniffing must have unit tests on fixture bytes.

## Phase 3: Model and RDF emitter

Goal: the normalised profile JSON and its SHACL serialisation, before any
real engine exists.

- [x] `autoprof/model.py`: dataclasses for `Structure`, `Part`, `Field` and
  `Profile`, matching the JSON interchange in [02-model.md](02-model.md)
  (a superset of Frictionless Table Schema).
- [x] `autoprof/emit.py`:
  - `out/profiles/*.json` → `out/parts/*.nt`.
  - Mint IRIs from `BASE_IRI`.
  - Link `dct:conformsTo` from every distribution in the group.
  - Write the Table Schema → SHACL mapping, the optional `cube:Constraint`
    (with the confidence rule), `prof:observed`, provenance, and the status
    stubs for skipped and failed distributions.
- [x] Copy `vocab/prof.ttl` into the parts.
- [x] `shapes.ttl`: every `prof:Structure` has at least one `dct:hasPart`;
  every `sh:PropertyShape` has `sh:name`, `sh:path` and `sh:order`; every
  structure has `prov:wasGeneratedBy`.
- [x] `checks/`:
  - `no-orphan-shapes.rq`
  - `conformsTo-resolves.rq` (every `dct:conformsTo` target exists)
  - `status-set.rq` (every resolved distribution has a structure or a
    status)
- [x] Golden-file tests: fixture profile JSON → expected Turtle. Include the
  `bevoelkerung` example from 2026-11-03, which must give the `cube.ttl`
  equivalent.

Done when the golden tests pass and the output validates with
`scripts/validate.sh`.

## Phase 4: Tabular engine

Goal: real structures for CSV, XLSX, XLS, ODS, Parquet and tabular JSON.

- [x] Port `infer_tabular.py` (2026-11-03 prototype) to `autoprof/engines/tabular.py`:
  - Frictionless `describe` for field names and types.
  - DuckDB for `sniff_csv`, `SUMMARIZE`, samples and distinct values when there
    are 50 or fewer.
  - Type reconciliation: DuckDB dates win over a Frictionless `string`.
  - Categorical and boolean-candidate hints, missing-value tokens.
- [x] One part per sheet for XLSX, XLS and ODS. Detect header rows (skip
  leading title rows, merged header lines) and record them as
  `csvw:dialect`.
- [x] JSON only when the root, or a single top-level array property, holds
  records; otherwise hand over to the tree engine (phase 7).
- [x] DuckDB connection: `memory_limit=512MB`, `threads=2`, a temp directory
  under `out/tmp`.

Done when all tabular test datasets produce structures in visoto-qlever
after a manual import (check with the visoto MCP), and the run is under 5
minutes for the test list.

## Phase 5: Geo engine

- [x] `ST_Read` via DuckDB `spatial`:
  - SHP inside ZIP (`/vsizip/`), GPKG and GML.
  - WFS from `DescribeFeatureType` plus the `GetFeature` sample.
- [x] One part per layer, with `prof:geometryType`, `prof:crs`, a geometry
  field (`geo:wktLiteral`), and attribute fields as in tabular, including
  stats.
- [x] Fall back to `ogrinfo -json -so` (pyogrio) if `ST_Read` fails on a
  driver.

Done when the SHP, GPKG, GML and WFS test datasets have structures with CRS
and geometry type.

## Phase 6: PX engine

- [x] Parse `.px` with pyaxis. For PxWeb (`PX|JSON`), use the table metadata
  endpoint instead of downloading data.
- [x] Dimensions, with codes and labels per language, become
  `cube:KeyDimension` with `sh:in`. The content variable becomes
  `cube:MeasureDimension`, with `UNITS` mapped to `qudt:unit` where possible
  and kept as a literal otherwise. `TIMEVAL` becomes `meta:dataKind`.
- [x] Always emit `cube:Constraint`.

Done when the PX test datasets produce a `cube:Constraint` that validates.

## Phase 7: Tree engine (JSON, XML)

- [x] **JSON:** use genson to infer a JSON Schema from the sample, then map it
  to SHACL with `sh:node` for nested objects and `sh:maxCount` from array or
  object. Paths are JSON Pointer style names under the column IRI.
- [x] **XML:** if `xsi:schemaLocation` points to a reachable XSD, map its
  elements and types. Otherwise build element/attribute path statistics with
  lxml (counts, optionality, leaf value types inferred like tabular) and map
  them to nested node shapes.
- [x] Detect GML, RDF/XML and GeoJSON and route them to their own engines, or
  record them as skipped.

Done when the JSON and XML test datasets produce nested structures, with a
depth limit of 6 and a property limit of 200 per node.

## Phase 8: RDF engine

- [x] Parse the sample with rdflib, with a triple cap
  (`SAMPLE_ROWS × 10`). Run sheXer to get SHACL, and keep the constraint
  support ratios as `prof:observed`.
- [x] Profile one serialisation per group (prefer Turtle).

Done when the RDF test datasets produce shapes per class.

## Phase 9: Hardening and first real run

- [x] `out/report.md`:
  - Counts per family and status.
  - The declared-versus-sniffed mismatch table.
  - The 20 slowest distributions and the failures with their reasons.
- [x] Run on a larger list (about 500 datasets drawn from the 2026-11-03
  selection) and fix the top failure causes.
- [x] Document the import in `01-purpose.md`: upload `out/auto-profiling.ttl`
  to `visoto-qlever`, graph `urn:data:auto-profiling-githubpipeline`, using
  replace on load, which is an open question for the i14y pipeline as well.
- [ ] Verify the import with the visoto MCP: count `prof:Structure`,
  `sh:PropertyShape` and `cube:Constraint`, and spot-check 3 datasets.

Done when the larger run finishes unattended, with failures explained in the
report.

## Implementation notes (2026-11-03)

Where the implementation differs from, or adds to, the plan above:

- **Cache location:** `scripts/run.sh` wipes `raw/` before every fetch, so the
  ETag/Last-Modified cache and its samples live in `cache/` (gitignored);
  `raw/samples/` holds hard links to them.
- **`${VAR:-default}` in `pipeline.env`:** `BASE_IRI`, `SAMPLE_ROWS` and
  `DATASETS` can be overridden from the environment
  (`DATASETS=datasets-large.txt scripts/run.sh auto-profiling`).
- **Equivalence groups:** Opendatasoft exports form two groups per table: the
  table exports (Parquet representative) and the RDF exports (Turtle
  representative), so the RDF engine profiles the publisher's own RDF model.
  PxWeb links to one table (per language, and BFS `/asset/` pages) form one
  group. Each group lists up to three fallbacks, tried when the
  representative fails.
- **Fetch:** one streamed GET serves both the 64 KB sniff and the sample (after
  a HEAD for validators and size), instead of a separate ranged GET. Range
  requests are used where the tail matters: Parquet footers and ZIP central
  directories of files above `MAX_DOWNLOAD_MB` (read through a sparse local
  file). XML samples may be truncated (parsed with recovery); JSON, GML and
  RDF/XML must fit the limit. The XSD named by `xsi:schemaLocation` is fetched
  next to an XML sample.
- **WFS:** `WFS_MAX_LAYERS` (20) layers per service and `WFS_FEATURES` (1000)
  features per layer instead of `count=SAMPLE_ROWS`: services list hundreds of
  layers.
- **PxWeb:** the table metadata JSON in every available language (de, fr, it,
  en) plus a one-cell PX from a POST query, which carries the keywords the
  JSON lacks (`UNITS`, `CONTVARIABLE`, `DECIMALS`, `TIMEVAL`). Without
  `CONTVARIABLE` there is one measure (`value`), and every variable, including
  a "Variable" dimension, is a key dimension.
- **Geo:** curve geometries (MultiCurve, CompoundCurve, ...) that DuckDB can't
  convert are read with `keep_wkb=true`; the CRS falls back to the GML
  `srsName`; INTERLIS bookkeeping tables (`T_ILI2DB_*`) are skipped.
- **RDF:** sheXer writes `sh:dataType`; it is read back as `sh:datatype`.
  Support ratios and value statistics are computed per class and predicate
  with rdflib (`prof:support`), and properties below sheXer's threshold are
  kept as optional.
- **Statuses** are IRIs (`prof:profiled`, `prof:skipped`, `prof:failed`); a
  skipped or failed structure carries a reason and no parts, and every
  distribution of its group points to it. Distributions are typed
  `dcat:Distribution` and linked from their dataset, so the output is usable
  without the ODS catalogue.
- **Statistics as literals:** `prof:mean`, `prof:std`, `prof:nullPercentage`
  and `prof:support` are `xsd:decimal` rounded to 4 places; min, max and
  quartiles take the field's datatype where valid.
- **Extra vocabulary:** `prof:codeLabel` (SKOS notation and labels per
  language, PX), `prof:unitLabel`, `prof:sourceName`, `prof:format`,
  `prof:dateFormat`, `prof:recordsPath`, `prof:support`, `prof:maxItems`,
  `prof:categorical`, `prof:booleanCandidate`; see `vocab/prof.ttl`.
- **Test list:** 14 datasets in `datasets.txt`; `datasets-large.txt` holds the
  500-dataset sample for phase 9.
