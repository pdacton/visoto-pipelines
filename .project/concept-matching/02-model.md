# Model

## Targets

| Evidence from profiling | Target | Source |
|---|---|---|
| Observed codes overlap a code list | enumerated `mdr:ValueDomain` | LINDAS scheme, wrapped |
| Datatype, pattern, value range | described `mdr:ValueDomain` | I14Y API concept |
| Slot name, label, description | `mdr:DataElementConcept` | none yet (weakest) |
| Both of the above | `mdr:DataElement` | created on confirmation |
| Container name, slot set | `mdr:ObjectClass` | none yet |

## Wrapped code lists

```turtle
<…/vd/DV_KT_BEZ_GDE_SNAP/2024.1.0> a mdr:ValueDomain ;
    dcterms:identifier "DV_KT_BEZ_GDE_SNAP" ;
    mdr:permissibleValues <https://register.ld.admin.ch/i14y/concept/DV_KT_BEZ_GDE_SNAP/version/2024.1.0> ;
    skos:closeMatch <https://register.ld.admin.ch/i14y/concept/DV_KT_BEZ_GDE_SNAP/version/2024.1.0> ;
    sh:nodeKind sh:IRI .
```

One value domain per scheme version: code sets change between versions
(municipalities by year), and the observed values pick the version. Only the
wrappers (≈728 small resources) live in visoto-qlever.

## Candidates

```turtle
<slot> ap:candidate [
    a ap:Candidate ;
    ap:concept <…/vd/DV_KT_BEZ_GDE_SNAP/2024.1.0> ;   # range: DEC | VD | DE (| ObjectClass on containers)
    ap:candidateRank 1 ;
    ap:candidateScore 0.97 ;
    ap:evidence [ ap:method "code-overlap" ; ap:score 0.97 ;
                  ap:containment 1.0 ; ap:coverage 0.27 ; ap:level <…/level_1> ] ;
    prov:wasGeneratedBy <run> ] .
```

- `ap:evidence` (new) records each method's partial score, so a reviewer sees
  why a candidate was proposed. Methods: `code-overlap`, `datatype`,
  `pattern`, `range`, `name`.
- `ap:Match` keeps the candidate's score and adds `prov:wasAttributedTo`.

## Code-overlap scoring

The raw hit count is not enough: seven canton codes hit `DV_KT_BEZ_GDE_SNAP`
7/7, but also ISO 3166 alpha-2 4/7 (`BE` Belgium, `GE` Georgia).

- **containment**: share of the slot's distinct values found in the scheme
  (or one xkos level of it). Must be high.
- **coverage**: share of the scheme level's codes seen in the slot. Low is
  normal for samples and subsets, but breaks ties between a 26-code and a
  250-code list.
- Score per xkos level for hierarchical schemes (canton / district /
  municipality in one scheme).
- Among versions with equal containment, prefer the one with the best
  coverage, then the latest.

## Vocabulary changes (metadata-swiss)

- `ap:concept`: range `mdr:DataElementConcept`, `mdr:ValueDomain`,
  `mdr:DataElement`, `mdr:ObjectClass`.
- New `ap:evidence` and its properties; `ap:candidateScore` domain
  `ap:Candidate` or `ap:Match`.
- `ap:candidate` / `ap:match` domain extended to `ap:Container`.
- `mdr-shapes.ttl`: allow an `mdr:DataElement` without a data element concept
  while the registry is being built up.
