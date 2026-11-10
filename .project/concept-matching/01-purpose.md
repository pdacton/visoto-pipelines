# Purpose

Propose, for every profiled slot, which registered meaning and representation
it carries, so a reviewer can confirm matches and visoto can show "this column
holds canton codes (I14Y `DV_KT_BEZ_GDE_SNAP`, version 2024.1.0)".

Status: **design** (2026-11-10).

## Decisions (2026-11-10)

- **Three target types.** A candidate or match points to an
  `mdr:DataElementConcept` (meaning), an `mdr:ValueDomain` (representation) or
  an `mdr:DataElement` (both). The class of the target says which aspect was
  matched; there is no separate aspect property. Evidence often supports only
  one side: a column of canton codes is a sure value domain match while its
  meaning (residence? workplace?) stays open.
- **Value domains dominate.** Code-list overlap is the strongest evidence and
  the best-populated source. Data element concepts are the weakest target
  type: no source splits concepts into object class and property.
- **Container level.** A container gets candidates and matches for an
  `mdr:ObjectClass`, replacing the direct `ap:mainObjectClass` → `rdfs:Class`
  link.
- **Confirmed matches shape the slot.** A value domain match sets the slot's
  `sh:node`; a data element concept match sets its `sh:path` to the concept's
  ontology property. Both together make the slot a use of the data element
  (cardinality stays on the slot); if no such data element exists, confirming
  creates one, so the registry grows from profiling.
- **Code lists are wrapped, not copied.** Each LINDAS concept scheme gets an
  `mdr:ValueDomain` whose `mdr:permissibleValues` is the LINDAS scheme IRI.
  The 509k terms stay on LINDAS: visoto-qlever has too little memory, and
  LINDAS stays the single source of truth. The matcher queries LINDAS directly.
- **Separate pipeline.** The matcher is its own pipeline with its own graph,
  run after auto-profiling, so profiling runs on its own and a matcher rerun
  never reprofiles. It reads auto-profiling's profiles and points at its slot
  IRIs.
- **IRIs.** Data under `https://register.ld.admin.ch/mds/`, as the existing
  MDS data (`…/mds/agent/`, `…/mds/dataset/`). Vocabularies under
  `https://register.ld.admin.ch/mds/ontology/`: `ap:` moves to
  `…/mds/ontology/ap/`, `mdr:` to `…/mds/ontology/metadataregistry/`
  (from `…/i14y/ontology/…`).
- **Test data only.** The 657 I14Y structure property shapes on LINDAS with
  `dct:conformsTo` an I14Y concept evaluate the matcher. They are not imported
  as seed data elements.

## Sources

| Source | Gives | Notes |
|---|---|---|
| LINDAS graph `https://lindas.admin.ch/fso/i14y` | 728 versioned `skos:ConceptScheme`s (≈340 concepts), 509k `skos:Concept`s with `skos:notation`, xkos levels, version links | Code lists only (checked 2026-11-10) |
| I14Y API `https://api.i14y.admin.ch/api/public/v1` | Concepts that are not code lists: string, date, numeric with constraints | Only source for described value domains |
| LINDAS, same graph | 8,173 dataset-structure property shapes, 657 with `dct:conformsTo` a concept | Test data |

## Scope

In: candidates for slots and containers, scoring with recorded evidence,
the value domain wrappers, evaluation against the test data.

Out: a review UI for confirming matches (visoto, later), creating data element
concepts, matching against non-I14Y vocabularies.
