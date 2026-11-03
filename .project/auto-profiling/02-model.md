# Output model

Status: **decided**, apart from the open points in
[open-questions.md](open-questions.md).

Two layers, kept apart:

- **Structure:** what the data looks like, as SHACL. It is stable and
  reusable, and is the part visoto renders as "the schema".
- **Profile:** what was observed in the sample (counts, nulls, min/max,
  examples). It changes with every run and hangs off the structure via
  `prof:observed`, never inside the constraints.

## Alignment with I14Y

I14Y structures (copied by the `i14y` pipeline) use
`?dataset dct:conformsTo ?structure . ?structure dct:hasPart ?nodeShape`.
The same pattern is used here, so visoto templates can treat both alike:

```
dcat:Distribution ──dct:conformsTo──▶ prof:Structure ──dct:hasPart──▶ sh:NodeShape (one per sheet or layer)
                                                                          └─sh:property─▶ sh:PropertyShape
```

- An Opendatasoft dataset with 8 exports (CSV, XLSX, Parquet, JSON, Turtle and
  so on) is profiled **once**, from its preferred representative (Parquet,
  then CSV, then XLSX, then the rest). Every equivalent distribution points to
  the same structure via `dct:conformsTo`.
- Multi-sheet XLSX and multi-layer GPKG files give one `sh:NodeShape` per
  sheet or layer, all under one structure.

## IRIs

All minted IRIs sit under the configurable `BASE_IRI` set in `pipeline.env`
(default `https://example.org/auto-profiling/`). Identifiers are derived from
the distribution IRI, so reruns give the same IRIs:

| Resource | IRI |
|---|---|
| Structure | `{BASE_IRI}structure/{id}` (`id` = first 16 hex characters of sha256 of the representative distribution IRI) |
| Node shape | `{BASE_IRI}structure/{id}/{part-slug}` (`main` for single-part files) |
| Property shape | `{BASE_IRI}structure/{id}/{part-slug}/{field-slug}` |
| Column path | `{BASE_IRI}structure/{id}/{part-slug}/col/{field-slug}` (used as `sh:path` when the format has no predicates) |
| Profiling run | `{BASE_IRI}run/{timestamp}` |
| Profile vocabulary | `{BASE_IRI}prof#`, defined in `pipelines/auto-profiling/vocab/prof.ttl` and shipped in the output |

Profiles are blank nodes, since they are per-run values.

## Terms

| Concept | Term | Notes |
|---|---|---|
| Structure | `prof:Structure`, `dct:hasPart`, `dct:format` (sniffed, EU file-type IRI), `prof:declaredFormat`, `prof:formatMatch` | |
| Part | `sh:NodeShape`, `rdfs:label` (sheet or layer name), `prof:rowCount` | `cube:Constraint` added when applicable (below) |
| Field | `sh:PropertyShape`, `sh:name`, `schema:name`, `sh:order`, `sh:path`, `sh:datatype`, `sh:minCount`, `sh:maxCount`, `sh:in`, `sh:pattern`, `sh:node` (nested JSON or XML) | |
| CSV dialect | `csvw:dialect [ csvw:delimiter ; csvw:header ; csvw:encoding ]` | tabular only |
| Geometry | `prof:geometryType`, `prof:crs` (EPSG IRI), `sh:datatype geo:wktLiteral` | geo only |
| Profile | `prof:observed [ prof:count, prof:nullPercentage, prof:distinct, prof:min, prof:max, prof:mean, prof:std, prof:q25, prof:q50, prof:q75, prof:example ]` | at most 3 examples, each truncated to 200 characters |
| Provenance | `prov:wasGeneratedBy {run}`; the run carries `prov:endedAtTime`, tool versions, `prof:sampleRows` | |
| Status | `prof:status` (`profiled`, `skipped`, `failed`) and `prof:statusReason` on the distribution's structure stub | so visoto can show why something has no structure |

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
