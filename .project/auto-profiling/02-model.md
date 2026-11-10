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
| Container | `sh:NodeShape` + `ap:Container`, `rdfs:label` (sheet or layer name), `ap:rowCount` | `cube:Constraint` added when applicable (below) |
| Slot | `sh:PropertyShape` + `ap:Slot`, `sh:name`, `schema:name`, `sh:order`, `sh:path`, `sh:datatype`, `sh:minCount`, `sh:maxCount`, `sh:in`, `sh:pattern`, `sh:node` (nested JSON or XML), `ap:sourceName`, `ap:format` (also the date format of a CSV), `ap:categorical`, `ap:booleanCandidate`, `ap:codeLabel`, `ap:unitLabel`, `ap:fingerprint` | |
| Logical source | `rml:LogicalSource`, `ap:container`, `rml:source` (the representative distribution), `ap:tableName`, `rml:referenceFormulation` (`rml:CSV`, `rml:JSONPath`), `rml:iterator` (records path as JSONPath, e.g. `$.results[*]`), `csvw:dialect [ csvw:delimiter ; csvw:header ; csvw:encoding ; csvw:skipRows ; csvw:headerRowCount ]` | top-level containers only |
| Geometry | `ap:geometryType`, `ap:crs` (EPSG IRI), `sh:datatype geo:wktLiteral` | geo only |
| Profile | `ap:observed [ a ap:Observation ; ap:count, ap:nullPercentage, ap:distinct, ap:minValue, ap:maxValue, ap:mean, ap:std, ap:q25, ap:q50, ap:q75, ap:example, ap:support, ap:maxItems, ap:maxPerInstance ]` | at most 3 examples, each truncated to 200 characters |
| Provenance | `prov:wasGeneratedBy {run}`; the run carries `prov:startedAtTime`, `prov:endedAtTime`, `ap:toolVersion`, `ap:sampleRows` | |
| Status | `ap:status` (`ap:profiled`, `ap:skipped`, `ap:failed`) and `ap:statusReason` on the distribution's structure stub | so visoto can show why something has no structure |

Not emitted yet, although defined in `ap:`: triples maps, sentinels,
functional dependencies, `ap:pattern`, `ap:valueHistogram`,
`ap:minLength`/`ap:maxLength`, `ap:mainObjectClass`. Candidates, matches and
the shortcuts to the registry come from the concept-matching pipeline.

## Value sample and `out/slots.jsonl`

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
| `sample` | the value sample |
| `fingerprint` | first 16 hex characters of sha256 over the normalised name (case, accents and separators folded), the datatype and the sorted sample; also in the graph as `ap:fingerprint` |

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
