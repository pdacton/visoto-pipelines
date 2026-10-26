# Source: I14Y

Bring in **all** public content of the Swiss I14Y interoperability platform.

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
  the pipeline converts JSON itself.
- No OpenAPI document found at the usual paths.
- Multilingual fields come as `{de, en, fr, it}` objects → language-tagged
  literals (visoto filters labels by `visoto:dispLang`).

## IRIs

Mint I14Y's own IRI scheme, so data lines up with anything already on LINDAS:

- dataset `https://register.ld.admin.ch/i14y/dataset/{identifier}`
- data service `https://register.ld.admin.ch/i14y/dataservice/{identifier}`
- public service `https://register.ld.admin.ch/i14y/publicservice/{identifier}`
- concept `https://register.ld.admin.ch/i14y/concept/{identifier}/version/{version}`
- mapping table `https://register.ld.admin.ch/i14y/mappingtable/{identifier}/version/{version}`

Target vocabulary: DCAT-AP CH for catalogue records, SKOS for concepts and
code lists.
