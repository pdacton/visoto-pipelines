# Plan

Status: design (2026-11-10). Rewritten the same day around the goal in
[01-purpose.md](01-purpose.md): a registry built bottom-up, and links from
every slot to it.

| Phase | Delivers |
|---|---|
| 0 | Vocabulary and auto-profiling prerequisites |
| 1 | Registry seed: code-list and identifier value domains |
| 2 | Slots linked to value domains: technical comparison works |
| 3 | Concepts found or created per slot: semantic comparison works |
| 4 | Operation: thresholds, review queue, reruns |

## Phase 0: Vocabulary and auto-profiling prerequisites

Vocabulary (`metadata-swiss/mds-datamodel/ontology/`):

- [ ] Move the namespaces: `ap:` → `https://register.ld.admin.ch/mds/ontology/ap/`,
  `mdr:` → `https://register.ld.admin.ch/mds/ontology/metadataregistry/`, in
  `autoprofiling/`, `dataelement/`, README and examples, and the `mdr:` prefix
  in visoto's `visoto.config` and `visoto.config.example`.
- [ ] Apply the [vocabulary changes](02-model.md#vocabulary-changes-metadata-swiss)
  and commit the `ap:` draft.
- [ ] Example in `autoprofiling/examples/`: two slots of different datasets
  linked to the same value domain and concept, with candidate, match and
  shortcut triples.

Auto-profiling (`pipelines/auto-profiling/`):

- [ ] Finish the open phase 9 item: verify an import into visoto-qlever, and
  settle whether the upload replaces or appends to a graph (pipeline graphs
  must be replaced; the confirmations graph must never be touched).
- [ ] Migrate from `prof:` to `ap:` (mapping table in `autoprofiling/README.md`).
  **Scope:** rename terms; type containers, slots and observations
  (`ap:Container`, `ap:Slot`, `ap:Observation`); move `csvw:dialect` and the
  records path to `rml:LogicalSource` with `ap:container` and `ap:tableName`.
  Not in scope: triples maps, sentinels, functional dependencies,
  `ap:pattern`, `ap:valueHistogram`. No visoto template or script uses
  `prof:`, so nothing breaks there.
- [ ] Rewrite `.project/auto-profiling/02-model.md` for `ap:` and the new IRIs;
  update golden-file tests.
- [ ] Set `BASE_IRI` to `https://register.ld.admin.ch/mds/`. IRIs stay derived
  from the representative distribution; they may change between runs (see
  [02-model.md](02-model.md#iri-stability)).
- [ ] **Value sample per slot, collected in the `profile` stage** (the engines
  hold the sample; `emit` does not), also for slots with more than 50 distinct
  values (6,931 slots had none in the last run). `sh:in` stays limited to 50
  values. Rerunnable offline from the cached samples (`--skip-fetch`).
- [ ] `emit` writes `out/slots.jsonl`, this pipeline's input: per slot its
  IRI, the [re-attach key](02-model.md#iri-stability), name, label, container
  and neighbouring slot names, datatype, unit, format, geometry type and
  coordinate reference system, min/max, distinct count, the value sample and
  the [fingerprint](02-model.md#fingerprints). Not part of the graph.
- [ ] Size check before any full run: about 11M triples for all ~35,500
  distributions (1M for 3,293 in the last run), against visoto-qlever's
  memory.

## Phase 1: Registry seed

New pipeline `pipelines/concept-matching/`, stage `registry`.

- [ ] Registry storage: `registry/*.jsonl` in the pipeline folder (value
  domains, concepts, object classes, properties, data elements), one entry
  per line with its IRI; the stage turns them into Turtle. Entries are only
  added or changed, never renumbered.
- [ ] Code lists: one value domain per LINDAS list and one per version (see
  [02-model.md](02-model.md#code-lists)), pointing at the LINDAS IRIs.
- [ ] Local code index: list, version, xkos level and notation of all codes,
  fetched from LINDAS into a DuckDB file in `cache/` (about 509k rows),
  refreshed when LINDAS has new versions.
- [ ] Identifier value domains: one per ID validator (AHV number, UID,
  EGID/EWID, postcode, …), written by hand with the rule's format and
  checksum.
- [ ] Shapes and checks: registry entries validate against `mdr-shapes.ttl`;
  every code-list wrapper's `mdr:permissibleValues` resolves on LINDAS.

Done when the registry graph loads into visoto-qlever and visoto shows a
value domain with its link to LINDAS.

## Phase 2: Links to value domains

Stage `link-values`, run after auto-profiling. No LLM.

- [ ] Input `out/slots.jsonl`; work once per fingerprint.
- [ ] Code lists: normalise values, join with the local code index, score
  containment and coverage per list level; link automatically only when
  unambiguous, otherwise keep the top 3 as candidates (rules in
  [02-model.md](02-model.md#linking-to-code-lists)).
- [ ] Identifiers: a slot whose values pass a validator at a high rate is
  linked to its value domain.
- [ ] Everything else: find or create the described value domain by rule
  (datatype, unit, format; geometry type and coordinate reference system).
- [ ] Output: candidates with evidence, automatic matches, shortcut triples
  (`ap:valueDomain`), validated by SHACL.
- [ ] Confirmations (interim): `confirmations.csv`, edited by hand (re-attach
  key, entry IRI, match type, who, when); stage `confirm` turns it into
  `out/confirmations.ttl` for the confirmations graph. A person's match
  overrides an automatic one and is offered to all slots with the same
  fingerprint (`confirmed-elsewhere`).
- [ ] Re-attach a person's matches to the current slot IRIs by their key;
  report those that cannot be placed or are ambiguous.
- [ ] Gold set, part 1 (`tests/gold-values.csv`): about 150 slots with the
  value domain they should get (or none), spread over engines and datatypes,
  including small-integer code columns. The run report gives precision and
  recall of the automatic links on it.

Done when the comparison query in
[02-model.md](02-model.md#what-the-links-make-possible) returns technically
comparable datasets on the 500-dataset run, and a match in
`confirmations.csv` survives an auto-profiling rerun that changes its slot's
IRI.

## Phase 3: Concepts

Stage `link-concepts`. Steps as in
[02-model.md](02-model.md#finding-or-creating-a-concept).

- [ ] Embedding index of the registry's object classes and properties (a
  local file), updated as entries are created.
- [ ] Per fingerprint: describe the slot, look up the nearest entries, let
  the LLM name the object class and the property (each existing or new), or
  answer "none"; in the same call it decides ambiguous code-list candidates
  from phase 2.
- [ ] Data element concepts by rule: the pair of object class and property
  (ISO/IEC 11179), created if missing.
- [ ] Value check on every answer; answers the data contradicts are dropped.
- [ ] New object classes, properties and concepts are written to `registry/`
  with status "candidate" and provenance.
- [ ] Data elements by rule: a slot with a concept and a value domain gets
  the data element for that pair, created if missing.
- [ ] Output: candidates with rationale, automatic matches above the
  confidence threshold, shortcut triples (`ap:dataElementConcept`,
  `ap:dataElement`).
- [ ] Cache answers by fingerprint, so a rerun only asks about new slots.
- [ ] Gold set, part 2 (`tests/gold-pairs.csv`): pairs of slots that should
  share a concept and pairs that should not. Concepts are created, so there
  is no fixed target to compare with; the report gives precision and recall
  on the pairs.

Done when the comparison query with `ap:dataElementConcept` returns
semantically comparable datasets on the 500-dataset run, and a second run
creates no new entries for unchanged slots.

## Phase 4: Operation

- [ ] Thresholds for automatic acceptance, set from the two gold sets.
- [ ] Review queue in the run report: one row per fingerprint, ordered by the
  number of slots it covers, with the candidates and their evidence.
- [ ] New datasets: a run on new input links their slots to the existing
  registry and creates entries only where nothing fits.
- [ ] Reruns: automatic links are regenerated; a person's matches are
  re-attached and re-checked against the new values, and contradictions are
  flagged in the report (drift).
- [ ] Registry report: entries by kind and status, entries with the most
  slots, entries with a single slot.

## Later

- **Pruning:** merging duplicate concepts, object classes and properties in
  the knowledge graph; the replaced entry points to its replacement and the
  links follow.
- A review UI in visoto that writes a person's matches to the confirmations
  graph, replacing `confirmations.csv`.
- Converting datasets to RDF: target shapes, RML (triples maps, sentinels),
  conversion and validation of the converted data.
- Superset structures: one structure for slightly diverging distributions.
- Functional dependencies, patterns and value histograms in auto-profiling.
