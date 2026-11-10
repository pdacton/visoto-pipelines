# Plan

Status: design (2026-11-10). Phases 1–3 give a usable matcher for code lists,
the dominant case; phases 4–5 add the weaker evidence.

## Phase 0: Vocabulary

- [ ] Move the namespaces: `ap:` → `https://register.ld.admin.ch/mds/ontology/ap/`,
  `mdr:` → `https://register.ld.admin.ch/mds/ontology/metadataregistry/`, in
  `metadata-swiss/mds-datamodel/ontology/` (`autoprofiling/`, `dataelement/`,
  README, examples) and the `mdr:` prefix in visoto's `visoto.config` and
  `visoto.config.example`.
- [ ] Apply the [vocabulary changes](02-model.md#vocabulary-changes-metadata-swiss)
  in `metadata-swiss/mds-datamodel/ontology/` and commit the `ap:` draft.
- [ ] Example: one slot with a code-overlap candidate and a confirmed match in
  `autoprofiling/examples/`.
- [ ] Migrate auto-profiling from `prof:` to `ap:` (mapping table in
  `autoprofiling/README.md`): containers and slots typed `ap:Container` /
  `ap:Slot`, observations typed, `csvw:dialect` and records path moved to
  `rml:LogicalSource`. Golden-file tests updated.
- [ ] Set auto-profiling's `BASE_IRI` to `https://register.ld.admin.ch/mds/`
  (structures, containers and slots below it).

## Phase 1: Value domain wrappers

Extend the `i14y` pipeline (it already runs `CONSTRUCT` against LINDAS for the
schemes).

- [ ] One enumerated `mdr:ValueDomain` per scheme version, pointing to the
  LINDAS scheme IRI. No terms copied.
- [ ] Described value domains from I14Y API concepts that are not code lists
  (datatype, pattern, range).
- [ ] Shapes and checks: every wrapper's `mdr:permissibleValues` resolves on
  LINDAS.

## Phase 2: Test set

- [ ] Extract the 657 property shapes with `dct:conformsTo` a concept: name,
  datatype, concept, dataset.
- [ ] The shapes rarely carry values (`sh:in` on 49), so profile the
  distributions of their datasets with auto-profiling to get observed values.
- [ ] Record how many test slots end up with observed values; that is the
  evaluation base.

## Phase 3: Code-overlap matcher

- [ ] New pipeline `pipelines/concept-matching/` with its own graph
  (`urn:data:concept-matching-githubpipeline`), run after auto-profiling.
- [ ] Input: auto-profiling profiles (categorical slots and their distinct
  values).
- [ ] Batched `VALUES` queries against LINDAS (`skos:notation`, grouped by
  scheme and xkos level), polite rate and caching like auto-profiling's fetch.
- [ ] Scoring as in [02-model.md](02-model.md#code-overlap-scoring); top 3
  candidates per slot with evidence.
- [ ] Evaluate on the test set: precision@1, recall, wrong-version rate.

## Phase 4: Described value domains

- [ ] Compatibility of datatype, pattern and range with described value
  domains. Weak on its own ("integer, 1–12"); mainly a tie-breaker and a
  filter.

## Phase 5: Names

- [ ] Slot name and label against concept labels in de/fr/it/en.
- [ ] Container candidates for `mdr:ObjectClass`, once object classes exist.

## Done when

- `scripts/run.sh` produces candidates with evidence for every categorical
  slot, validated by SHACL.
- Test-set results are reported in the run report.
