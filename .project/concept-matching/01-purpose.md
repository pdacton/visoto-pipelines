# Purpose

Build a metadata registry in the knowledge graph, so that datasets can be
compared and similar ones found:

- **technically interoperable:** their slots share a value domain (the same
  code list, or the same datatype, unit and format);
- **semantically interoperable:** their slots share a data element concept
  (the same object class and property);
- **both:** their slots share a data element.

The registry is extracted bottom-up from the data. Each slot (column, field)
of an auto-profiled structure is linked on its own to a registry entry, found
or newly created. Slots of different datasets that end up at the same entry
form the clusters; there is no grouping step.

The pipeline only **establishes the connections**. Finding similar datasets
is a SPARQL query on the knowledge graph, not part of the pipeline.

Status: **design** (2026-11-10).

## Decisions (2026-11-10)

Registry:

- **Three kinds of entry a slot links to.** An `mdr:ValueDomain`
  (representation), an `mdr:DataElementConcept` (meaning: object class plus
  property), and an `mdr:DataElement` (the pair of both). Evidence often
  supports only one side: a column of canton codes surely has the canton value
  domain while its meaning (residence? workplace?) is a separate question.
- **Code lists are wrapped, not copied.** Each LINDAS code list gets a value
  domain for the list and one per version beneath it, pointing at the LINDAS
  IRIs. The 509k codes stay on LINDAS and are not loaded into visoto-qlever
  (too little memory). For matching, the pipeline keeps the codes in a local
  DuckDB file in its cache.
- **List and versions.** A slot links to the most specific entry its values
  support. Two datasets on different versions of the same list still meet at
  the list entry.
- **Value domains for everything else are made by rule,** without an LLM:
  datatype plus unit plus format; for geometries, geometry type plus
  coordinate reference system; for identifiers, the validator that recognises
  them (AHV number, UID, EGID).
- **Concepts come from the data.** For each slot, existing entries are looked
  up (embeddings), and an LLM decides whether one of them fits or a new one
  is created. Nothing is imported from I14Y; where an I14Y concept
  corresponds, it is linked with `skos:closeMatch`.
- **Concepts are specific and follow ISO/IEC 11179.** A data element concept
  is exactly one object class plus one property. The object class is the
  kind of thing the record describes (Person), the property its
  characteristic (municipality of residence). The LLM finds or creates the
  object class and the property, each on its own; the data element concept is
  the pair of the two and is created by rule. "Municipality of residence" and
  "municipality of work" are therefore different concepts. Coarser similarity
  needs no coarser concepts: it comes from the parts two slots share (the
  object class, the property, or the value domain).
- **Duplicates are accepted.** The lookup "does this concept already exist?"
  is the critical step, and it will miss sometimes. Duplicate concepts are
  merged later by a separate pruning process in the knowledge graph.
- **The registry is state, not output.** Created entries must keep their IRIs
  across runs, so they are stored as files in the repo
  (`pipelines/concept-matching/registry/`) and published from there.

Links:

- **Proposal, accepted link, shortcut.** An `ap:Candidate` is a scored
  proposal with its evidence. An `ap:Match` is an accepted link, attributed
  to a person or to the run that accepted it automatically. Every match also
  gives a direct triple on the slot (`ap:valueDomain`,
  `ap:dataElementConcept`, `ap:dataElement`), so comparison queries stay
  short.
- **The slot's shape is never changed.** Links are extra triples about the
  slot in the concept-matching graph; the slot keeps describing the source
  data.
- **Work per fingerprint.** Slots with the same name, datatype and values are
  processed once and the result applies to all of them (27,677 slots but
  8,761 fingerprints in the last 500-dataset run). A full run has about 300k
  slots, so automatic acceptance above a threshold is required.
- **Confirmations.** A person's confirmations go into visoto-qlever in their
  own named graph. Until a review UI exists they are entered in
  `confirmations.csv` in the repo and uploaded from there. Slot IRIs may
  change between runs; confirmations carry a key to be re-attached.
- **Quality is measured** on hand-labelled slots (the gold set).

Setup:

- **Separate pipeline,** run after auto-profiling, so profiling runs on its
  own and a rerun here never reprofiles.
- **IRIs.** Data under `https://register.ld.admin.ch/mds/`. Vocabularies under
  `https://register.ld.admin.ch/mds/ontology/`: `ap:` at `…/ap/`, `mdr:` at
  `…/metadataregistry/` (moved from `…/i14y/ontology/…`).

## Sources

| Source | Gives | Notes |
|---|---|---|
| auto-profiling (`out/slots.jsonl`) | Slots with names, datatypes, statistics and value samples | The data the registry is extracted from |
| LINDAS graph `https://lindas.admin.ch/fso/i14y` | 728 versioned code lists (about 340 lists), 509k codes with `skos:notation` and xkos levels | Wrapped as value domains |

## Scope

In: the registry (value domains, data element concepts, object classes,
properties, data elements), links from slots to its entries with recorded
evidence, the interim confirmations file, the gold set, re-attaching
confirmations after reruns.

Later: merging duplicate entries (pruning), a review UI in visoto, converting
datasets to RDF (RML, target shapes, validation of the converted data).

Not planned: similarity search as a pipeline step (it is a SPARQL query),
importing I14Y concepts, publishing to I14Y or OpenMetadata.
