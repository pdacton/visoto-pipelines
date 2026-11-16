# Output model

Status: **decided**, apart from the open points in
[open-questions.md](open-questions.md).

The output vocabulary is `ap:` (`https://register.ld.admin.ch/mds/ontology/ap/`),
maintained in metadata-swiss/mds-datamodel `ontology/autoprofiling/` and copied
to `pipelines/auto-profiling/vocab/` (`ap.ttl`, `ap-shapes.ttl`). It replaced
the pipeline's own `prof:` vocabulary on 2026-11-10; the mapping is in that
folder's README.

Three layers, kept apart:

- **Structure:** what the data looks like, as SHACL. It is stable and
  reusable, and is the part visoto renders as "the schema". Node shapes are
  also `ap:Container`, property shapes also `ap:Slot`.
- **Profile:** what was observed in the sample (counts, nulls, min/max,
  examples). It changes with every run and hangs off the slot via
  `ap:observed`, never inside the constraints.
- **Physical description:** where a container is read from, as an
  `rml:LogicalSource` (distribution, sheet or layer, records path, CSV
  dialect).

## Alignment with I14Y

I14Y structures (copied by the `i14y` pipeline) use
`?dataset dct:conformsTo ?structure . ?structure dct:hasPart ?nodeShape`.
The same pattern is used here, so visoto templates can treat both alike:

```
dcat:Distribution ──dct:conformsTo──▶ ap:DataStructure ──dct:hasPart──▶ ap:Container (sh:NodeShape, one per sheet or layer)
        ▲                                                                   └─sh:property─▶ ap:Slot (sh:PropertyShape)
        └──rml:source── rml:LogicalSource ──ap:container──▶ (the container)
```

- An Opendatasoft dataset with 8 exports (CSV, XLSX, Parquet, JSON, Turtle and
  so on) is profiled **once**, from its preferred representative (Parquet,
  then CSV, then XLSX, then the rest). Every equivalent distribution points to
  the same structure via `dct:conformsTo`.
- Multi-sheet XLSX and multi-layer GPKG files give one container per sheet or
  layer, all under one structure; each container's logical source names its
  sheet or layer with `ap:tableName`.
- The logical source reads the representative distribution
  (`ap:profiledDistribution`), which carries its `dcat:downloadURL` and
  `dcat:accessURL`.

## IRIs

All minted IRIs sit under the configurable `BASE_IRI` set in `pipeline.env`
(`https://register.ld.admin.ch/mds/`, decided 2026-11-10). Identifiers are
derived from the representative distribution IRI:

| Resource | IRI |
|---|---|
| Structure | `{BASE_IRI}structure/{id}` (`id` = first 16 hex characters of sha256 of the representative distribution IRI) |
| Container | `{BASE_IRI}structure/{id}/{part-slug}` (`main` for single-part files) |
| Logical source | `{BASE_IRI}structure/{id}/{part-slug}/source` |
| Slot | `{BASE_IRI}structure/{id}/{part-slug}/{field-slug}` |
| Nested container | `{slot}/node` |
| Column path | `{BASE_IRI}structure/{id}/{part-slug}/col/{field-slug}` (used as `sh:path` when the format has no predicates) |
| Profiling run | `{BASE_IRI}run/{timestamp}` |

Observations and CSV dialects are blank nodes, since they are per-run values.

IRIs are stable across reruns only while the representative stays the same.
A fallback, a new export format or a removed distribution changes the
representative and so every IRI of the structure. Links made by a person
therefore carry a re-attach key (dataset, distributions, container path,
source name), the same key `out/slots.jsonl` writes per slot; see
[concept-matching/02-model.md](../concept-matching/02-model.md#iri-stability).

## Terms

| Concept | Term | Notes |
|---|---|---|
| Structure | `ap:DataStructure`, `dct:hasPart`, `dct:format` (sniffed, EU file-type IRI), `ap:declaredFormat`, `ap:formatMatch`, `ap:engine`, `ap:profiledDistribution` | |
| Container | `sh:NodeShape` + `ap:Container`, `rdfs:label` (sheet or layer name), `ap:rowCount`, `ap:candidateKey`, `ap:functionalDependency [ a ap:FunctionalDependency ; ap:determinant ; ap:dependent ; ap:supportRows ; ap:determinantValues ; prov:wasGeneratedBy ]` | `cube:Constraint` added when applicable (below); keys and dependencies from tabular and geo samples only (below) |
| Slot | `sh:PropertyShape` + `ap:Slot`, `sh:name`, `schema:name`, `sh:order`, `sh:path`, `sh:datatype`, `sh:minCount`, `sh:maxCount`, `sh:in`, `sh:pattern`, `sh:node` (nested JSON or XML), `ap:sourceName`, `ap:format` (also the date format of a CSV), `ap:categorical`, `ap:booleanCandidate`, `ap:codeLabel`, `ap:unitLabel`, `ap:fingerprint` | |
| Logical source | `rml:LogicalSource`, `ap:container`, `rml:source` (the representative distribution), `ap:tableName`, `rml:referenceFormulation` (`rml:CSV`, `rml:JSONPath`), `rml:iterator` (records path as JSONPath, e.g. `$.results[*]`), `csvw:dialect [ csvw:delimiter ; csvw:header ; csvw:encoding ; csvw:skipRows ; csvw:headerRowCount ]` | top-level containers only |
| Geometry | `ap:geometryType`, `ap:crs` (EPSG IRI), `sh:datatype geo:wktLiteral` | geo only |
| Profile | `ap:observed [ a ap:Observation ; ap:count, ap:nullPercentage, ap:distinct, ap:minValue, ap:maxValue, ap:mean, ap:std, ap:q25, ap:q50, ap:q75, ap:example, ap:pattern, ap:support, ap:maxItems, ap:maxPerInstance ]` | at most 3 examples, each truncated to 200 characters; `ap:pattern` for string slots (below) |
| Provenance | `prov:wasGeneratedBy {run}`; the run carries `prov:startedAtTime`, `prov:endedAtTime`, `ap:toolVersion`, `ap:sampleRows` | |
| Status | `ap:status` (`ap:profiled`, `ap:skipped`, `ap:failed`) and `ap:statusReason` on the distribution's structure stub | so visoto can show why something has no structure |

Not emitted yet, although defined in `ap:`: triples maps, sentinels,
`ap:valueHistogram`,
`ap:minLength`/`ap:maxLength`, `ap:mainObjectClass`. Candidates, matches and
the shortcuts to the registry come from the concept-matching pipeline.

## Candidate keys and functional dependencies

The tabular and geo engines check each container's sample (at most
`SAMPLE_ROWS` rows) for single-column keys and dependencies. Both are
evidence from a sample, never constraints.

- **Candidate key:** a slot with a value in every row, all distinct.
  Decimals are left out, because a measure can be unique by chance.
- **Functional dependency:** slot A determines slot B when each value of A
  comes with exactly one value of B in the rows where A is set (B's nulls are
  ignored). A must be a string or integer, must not be a candidate key, and
  must repeat: at least 3 values, and on average 2 rows per value. Nothing is
  reported below 50 rows, nor for containers with more than 120 slots.
  Constant slots neither determine nor depend. One `ap:FunctionalDependency`
  per determinant lists all its dependents; `ap:supportRows` and
  `ap:determinantValues` say how strong the evidence is.
- Composite keys are not looked for. A code and its label determine each
  other, so they appear as two dependencies (`bfs_nr ↔ gemeinde_name`).

Concept matching uses them to decide a column's object class: the dependents
of a key that points to another entity belong to that entity.

## Pattern

`profile` derives a pattern for every string slot from its value sample (all
engines). Each value is cut into runs of digits, runs of letters and single
other characters. The most common sequence of run kinds must cover 95% of at
least 5 values. A run that is the same in every value stays literal;
otherwise digits become `\d` and letters `[A-Z]`, `[a-z]`, `[A-Za-z]` or
`\p{L}` (non-ASCII), with the observed length range:
`CHE-123.456.789` → `^CHE\-\d{3}\.\d{3}\.\d{3}$`, `BE` → `^[A-Z]{2}$`. Free
text has no dominant shape and gets none. The syntax is XPath's, as for
`sh:pattern`. Whether a pattern is specific enough to define a value domain
is decided by concept matching, not here.

## Value sample, `out/slots.jsonl` and `out/containers.jsonl`

The `profile` stage keeps up to `VALUE_SAMPLE` (200) distinct values per
field, chosen by their md5 hash so the same values give the same sample on
every run, each truncated to 200 characters. It is collected for every field
with values, including those with more than 50 distinct values (`sh:in` stays
limited to 50 categorical values). Geometry columns, nested objects and
Parquet files read from their footer only have no sample.

The sample is not part of the graph. `emit` writes it to `out/slots.jsonl`,
one line per slot, the input of the concept-matching pipeline:

| Key | Content |
|---|---|
| `iri`, `structure`, `engine` | the slot, its structure and the engine that profiled it |
| `key` | re-attach key: `dataset`, `distributions` (all of the structure), `container` (path below the structure, e.g. `main` or `main/address/node`), `sourceName` |
| `name`, `label`, `description` | source name, title (PX) and description |
| `container` | `iri`, `path`, `label`, `tableName`, number of `slots`, `geometryType`, `crs` |
| `neighbours` | source names of up to 5 slots on each side |
| `type`, `datatype`, `nested`, `unit`, `unitLabel`, `format` | Table Schema type, `sh:datatype`, whether the slot has a nested container, QUDT unit, published unit, format |
| `min`, `max`, `distinct`, `count`, `nullPercentage`, `categorical` | observed statistics |
| `sample`, `pattern` | the value sample and its pattern |
| `fingerprint` | first 16 hex characters of sha256 over the normalised name (case, accents and separators folded), the datatype and the sorted sample; also in the graph as `ap:fingerprint` |

`emit` also writes `out/containers.jsonl`, one line per container (nested
ones included), so a model can see the whole table:

| Key | Content |
|---|---|
| `iri`, `structure`, `path`, `label`, `tableName`, `engine`, `rowCount`, `geometryType`, `crs` | the container |
| `dataset` | `iri` and, from `resolve`, `title` and `description` per language (`""` for untagged; description cut at 500 characters), `keywords` per language (without `opendata.swiss`), `themes` |
| `distribution` | `iri` and `title` of the representative distribution |
| `columns` | every slot in order: `name`, `label`, `datatype`, `pattern`, `slot` (IRI), `fingerprint` |
| `candidateKeys`, `dependencies` | source names; a dependency is `{determinant, dependents, rows, distinct}` |

All languages of the dataset context are kept, because datasets come from
every part of the country.

A rerun with `--skip-fetch` re-profiles from the cached samples in `raw/`,
so the value sample can be rebuilt without downloading again.

## Type mapping (Table Schema → SHACL)

The source is the mapper in [03-plan.md](03-plan.md), phase 3.

| Table Schema | `sh:datatype` |
|---|---|
| string | `xsd:string` |
| integer | `xsd:integer` |
| number | `xsd:decimal` |
| boolean | `xsd:boolean` |
| date | `xsd:date` |
| datetime | `xsd:dateTime` |
| time | `xsd:time` |
| year | `xsd:gYear` |
| yearmonth | `xsd:gYearMonth` |
| duration | `xsd:duration` |
| geojson / geopoint | `geo:wktLiteral` |

Constraints map as follows:

| Table Schema | SHACL |
|---|---|
| `required`, or 0% nulls observed | `sh:minCount 1` |
| `minimum` / `maximum` / `exclusive*` | `sh:minInclusive` / `sh:maxInclusive` / `sh:minExclusive` / `sh:maxExclusive` |
| `minLength` / `maxLength` / `pattern` | `sh:minLength` / `sh:maxLength` / `sh:pattern` |
| `enum`, or the observed values of a categorical field | `sh:in` |

## cube:Constraint

- **PX** always produces a `cube:Constraint`. PX dimensions become
  `cube:KeyDimension` with `sh:in` of their values; the content variable
  becomes `cube:MeasureDimension` with `qudt:unit` where `UNITS` maps.
- **Tabular** produces one only when the key/measure split is confident:
  - The key dimensions, being `primaryKey` plus temporal and categorical
    fields, must uniquely identify rows in the sample (a DuckDB
    `COUNT(DISTINCT keys) = COUNT(*)` check).
  - There must be at least one numeric non-key field.
  - Otherwise the output is plain SHACL.
- Cube annotations: `qudt:scaleType`, `meta:dataKind` for time dimensions, and
  `sh:closed true` with the `rdf:type` and `cube:observedBy` property shapes.
