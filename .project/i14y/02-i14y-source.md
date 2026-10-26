# Source: I14Y

Bring the public catalogue content of the Swiss I14Y interoperability
platform into visoto: datasets, data services, public services, catalogs and
concept schemes. Concepts and code-list entries are out of scope for now.

## API

Public JSON, no auth: `https://api.i14y.admin.ch/api/public/v1/`

Collections confirmed reachable on 2026-10-26 (sizes at `pageSize=1000`, page 1):

| Collection | Records |
|---|---|
| `datasets` | ≥ 1000 (page is full → must paginate) |
| `concepts` | 646 |
| `dataservices` | 80 |
| `publicservices` | 139 |
| `catalogs`, `mappingtables`, `agents` | reachable, not counted |

- `codelists` is **not** a top-level collection; code-list entries hang off
  each concept (one request per code-list concept).
- RDF export exists only per catalog: `catalogs/{id}/dcat/exports/ttl`
  (DCAT Turtle). Data services and public services have none, so their JSON
  is mapped here.
- Pagination: `pageSize` up to 1000, `page` from 1; an empty `data` array
  ends the list.
- No OpenAPI document found at the usual paths.
- Multilingual fields come as `{de, en, fr, it}` objects → language-tagged
  literals (visoto filters labels by `visoto:dispLang`).

## Already on LINDAS

LINDAS graph `https://lindas.admin.ch/fso/i14y` (checked 2026-10-26) holds
concepts with their code lists (460k `skos:Concept`) and 2,512 `dcat:Dataset`
with distributions, under the same `register.ld.admin.ch/i14y/...` IRIs.
Latest `dct:modified` is today, so it is kept current.

Missing there: data services, public services and catalogs.

## Split between the two sources

Everything ends up in the one published Turtle file, so visoto needs no
cross-endpoint or `GRAPH` queries.

| Content | Source | How |
|---|---|---|
| Datasets + distributions, publishers, documents, periods, relationships, attributions | LINDAS | `CONSTRUCT` against `https://ld.admin.ch/query`, copied as is |
| Agents (publishers) | LINDAS | copied with the datasets |
| Data services, public services | I14Y API | JSON → RDF with SPARQL Anything |
| Catalogs + their publishers | I14Y catalog export | Turtle, catalog records only (the datasets in it come from LINDAS) |
| Concept schemes (725) | LINDAS | `CONSTRUCT`, scheme triples only |
| Concepts, code-list entries (460k) | — | not copied for now; links from the schemes point to IRIs not in the file |
| Mapping tables | — | not copied for now |

## IRIs

Use I14Y's own IRI scheme, so the API-derived resources link up with the
datasets copied from LINDAS.

- dataset `https://register.ld.admin.ch/i14y/dataset/{identifiers[0]}`
- data service `https://register.ld.admin.ch/i14y/dataservice/{id}` — the
  internal id, as in I14Y's own catalog export (the I14Y MCP server uses
  `identifiers[0]` instead; the export wins so catalog links resolve)
- public service `https://register.ld.admin.ch/i14y/publicservice/{identifiers[0]}`
- agent `https://register.ld.admin.ch/i14y/agent/{identifier}`
- catalog `https://i14y.admin.ch/resources/dcat/catalogs/{id}` (from the export)
- theme/sector codes → `https://register.ld.admin.ch/i14y/concept/DV_DCAT_DATASET_THEME/{code}/version/1.1.0`,
  as LINDAS uses for datasets
- concept `https://register.ld.admin.ch/i14y/concept/{identifier}/version/{version}`
  (referenced only)

Target vocabulary for the API-derived part: DCAT-AP CH for data services
(matching I14Y's export), CPSV-AP for public services.

Data services and public services link to datasets by internal id; fetch
looks up the referenced datasets' identifiers (`raw/api/dataset-ids.json`).
