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
- No RDF/Turtle export endpoint was found (`.../dcat/exports/ttl` → 404), so
  the pipeline converts the JSON for anything not already on LINDAS.
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
| Data services, public services, catalogs | I14Y API | JSON → RDF with SPARQL Anything |
| Concept schemes (725) | LINDAS | `CONSTRUCT`, scheme triples only |
| Concepts, code-list entries (460k) | — | not copied for now; links from the schemes point to IRIs not in the file |
| Mapping tables, agents | — | not copied for now; publishers come with the datasets from LINDAS |

## IRIs

Use I14Y's own IRI scheme, so the API-derived resources link up with the
datasets copied from LINDAS.

- dataset `https://register.ld.admin.ch/i14y/dataset/{identifier}`
- data service `https://register.ld.admin.ch/i14y/dataservice/{identifier}`
- public service `https://register.ld.admin.ch/i14y/publicservice/{identifier}`
- concept `https://register.ld.admin.ch/i14y/concept/{identifier}/version/{version}`
  (referenced only)

Target vocabulary for the API-derived part: DCAT-AP CH, matching what LINDAS
uses for datasets.
