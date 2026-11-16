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
| 3b | Revision after review: object class per column in its table, with table and dataset context; patterns; labels and codes (open) |
| 4 | Operation: thresholds, review queue, reruns |

## Phase 0: Vocabulary and auto-profiling prerequisites

Vocabulary (`metadata-swiss/mds-datamodel/ontology/`):

- [x] Move the namespaces: `ap:` → `https://register.ld.admin.ch/mds/ontology/ap/`,
  `mdr:` → `https://register.ld.admin.ch/mds/ontology/metadataregistry/`, in
  `autoprofiling/`, `dataelement/`, README and examples, and the `mdr:` prefix
  in visoto's `visoto.config` and `visoto.config.example`.
- [x] Apply the [vocabulary changes](02-model.md#vocabulary-changes-metadata-swiss)
  and commit the `ap:` draft.
- [x] Example in `autoprofiling/examples/`: two slots of different datasets
  linked to the same value domain and concept, with candidate, match and
  shortcut triples.

Auto-profiling (`pipelines/auto-profiling/`):

- [x] Finish the open phase 9 item: verify an import into visoto-qlever, and
  settle whether the upload replaces or appends to a graph (pipeline graphs
  must be replaced; the confirmations graph must never be touched).
- [x] Migrate from `prof:` to `ap:` (mapping table in `autoprofiling/README.md`).
  **Scope:** rename terms; type containers, slots and observations
  (`ap:Container`, `ap:Slot`, `ap:Observation`); move `csvw:dialect` and the
  records path to `rml:LogicalSource` with `ap:container` and `ap:tableName`.
  Not in scope: triples maps, sentinels, functional dependencies,
  `ap:pattern`, `ap:valueHistogram`. No visoto template or script uses
  `prof:`, so nothing breaks there.
- [x] Rewrite `.project/auto-profiling/02-model.md` for `ap:` and the new IRIs;
  update golden-file tests.
- [x] Set `BASE_IRI` to `https://register.ld.admin.ch/mds/`. IRIs stay derived
  from the representative distribution; they may change between runs (see
  [02-model.md](02-model.md#iri-stability)).
- [x] **Value sample per slot, collected in the `profile` stage** (the engines
  hold the sample; `emit` does not), also for slots with more than 50 distinct
  values (6,931 slots had none in the last run). `sh:in` stays limited to 50
  values. Rerunnable offline from the cached samples (`--skip-fetch`).
- [x] `emit` writes `out/slots.jsonl`, this pipeline's input: per slot its
  IRI, the [re-attach key](02-model.md#iri-stability), name, label, container
  and neighbouring slot names, datatype, unit, format, geometry type and
  coordinate reference system, min/max, distinct count, the value sample and
  the [fingerprint](02-model.md#fingerprints). Not part of the graph.
- [x] Size check before any full run: about 11M triples for all ~35,500
  distributions (1M for 3,293 in the last run), against visoto-qlever's
  memory.

### Phase 0 results (2026-11-10)

Branches, committed, not pushed: `feat/mds-namespaces-concept-matching`
(metadata-swiss/mds-datamodel), `feat/ap-vocabulary` (this repo),
`chore/mdr-prefix-mds` (visoto). The 500-dataset run was re-profiled offline
with the new code (`--skip-fetch`).

- **Import:** the upload modal appends (Graph Store POST). Pipeline graphs are
  replaced by deleting the graph first or by a Graph Store PUT (QLever
  supports it); both act on one named graph, so the confirmations graph is
  never touched. Details in
  [auto-profiling/01-purpose.md](../auto-profiling/01-purpose.md#import-into-visoto).
- **Size:** 1.11M triples and 84 MB Turtle for 3,293 distributions; a full
  run extrapolates to ~12M triples and ~900 MB. That exceeds the upload limit
  (200 MB) and, as delta triples (~460 bytes each), would take ~5.5 GB of
  visoto-qlever's memory. **A full run needs another load path** (index
  rebuild or split graphs); decide before running it.
- **Slots:** 29,645 in `slots.jsonl` (29,126 leaves; 1,440 geometries).
  Every slot with more than 50 distinct values now has a sample (6,984).
  3,859 non-geometry leaves have none: 2,850 all null, 715 in empty layers,
  189 object or array values, 105 without statistics (Parquet footer, GDAL
  fallback).
- **Fingerprints:** 12,185 distinct (name, datatype, sample of up to 200
  values). The 8,761 of the review used a different definition; the new one
  splits more because the larger sample tells more columns apart.
- **Re-attach keys:** 8 keys are shared by two slots (the same source name
  twice in one container). Phase 2 must report them as ambiguous.
- `ap:mainObjectClass` now points to an `mdr:ObjectClass`; the three older
  `ap:` examples were changed accordingly.

### Working set: 100-dataset sample (2026-11-10)

Phases 1–3 run on `pipelines/auto-profiling/datasets-sample.txt`, 100
datasets drawn from the 500 by `uv run python -m autoprof sample` (rules in
`autoprof/sample.py`): only datasets with a profiled structure and at most
300 slots, at most 5 per publisher host, a minimum number of datasets per
concept-matching case (municipality codes 10, canton codes 6, labels instead
of codes 6, identifiers 6, small-integer codes 10) and per engine (tabular 35,
geo 30, PX 15, RDF 10, tree 10), the rest in hash order. Run it with
`DATASETS=datasets-sample.txt scripts/run.sh auto-profiling`. The gold sets
are drawn from it. The selection reads the output of a 500-dataset run; a
copy of that run's profiles and `slots.jsonl` is kept in
`pipelines/auto-profiling/cache/run-500/` (not in git).

## Phase 1: Registry seed

New pipeline `pipelines/concept-matching/`, stage `registry`.

- [x] Registry storage: `registry/*.jsonl` in the pipeline folder (value
  domains, concepts, object classes, properties, data elements), one entry
  per line with its IRI; the stage turns them into Turtle. Entries are only
  added or changed, never renumbered.
- [x] Code lists: one value domain per LINDAS list and one per version (see
  [02-model.md](02-model.md#code-lists)), pointing at the LINDAS IRIs.
- [x] Local code index: list, version, xkos level and notation of all codes,
  fetched from LINDAS into a DuckDB file in `cache/` (about 509k rows),
  refreshed when LINDAS has new versions.
- [x] Identifier value domains: one per ID validator (AHV number, UID,
  EGID/EWID, postcode, …), written by hand with the rule's format and
  checksum.
- [x] Shapes and checks: registry entries validate against `mdr-shapes.ttl`;
  every code-list wrapper's `mdr:permissibleValues` resolves on LINDAS.

Done when the registry graph loads into visoto-qlever and visoto shows a
value domain with its link to LINDAS.

## Phase 2: Links to value domains

Stage `link-values`, run after auto-profiling. No LLM.

- [x] Input `out/slots.jsonl`; work once per fingerprint.
- [x] Code lists: normalise values, join with the local code index, score
  containment and coverage per list level; link automatically only when
  unambiguous, otherwise keep the top 3 as candidates (rules in
  [02-model.md](02-model.md#linking-to-code-lists)).
- [x] Identifiers: a slot whose values pass a validator at a high rate is
  linked to its value domain.
- [x] Everything else: find or create the described value domain by rule
  (datatype, unit, format; geometry type and coordinate reference system).
- [x] Output: candidates with evidence, automatic matches, shortcut triples
  (`ap:valueDomain`), validated by SHACL.
- [x] Confirmations (interim): `confirmations.csv`, edited by hand (re-attach
  key, entry IRI, match type, who, when); stage `confirm` turns it into
  `out/confirmations.ttl` for the confirmations graph. A person's match
  overrides an automatic one and is offered to all slots with the same
  fingerprint (`confirmed-elsewhere`).
- [x] Re-attach a person's matches to the current slot IRIs by their key;
  report those that cannot be placed or are ambiguous.
- [x] Gold set, part 1 (`tests/gold-values.csv`): about 150 slots with the
  value domain they should get (or none), spread over engines and datatypes,
  including small-integer code columns. The run report gives precision and
  recall of the automatic links on it.

Done when the comparison query in
[02-model.md](02-model.md#what-the-links-make-possible) returns technically
comparable datasets on the 100-dataset sample, and a match in
`confirmations.csv` survives an auto-profiling rerun that changes its slot's
IRI.

## Phase 3: Concepts

Stage `link-concepts`. Steps as in
[02-model.md](02-model.md#finding-or-creating-a-concept).

- [x] Embedding index of the registry's object classes and properties (a
  local file), updated as entries are created.
- [x] Per fingerprint: describe the slot, look up the nearest entries, let
  the LLM name the object class and the property (each existing or new), or
  answer "none"; in the same call it decides ambiguous code-list candidates
  from phase 2.
- [x] Data element concepts by rule: the pair of object class and property
  (ISO/IEC 11179), created if missing.
- [x] Value check on every answer; answers the data contradicts are dropped.
- [x] New object classes, properties and concepts are written to `registry/`
  with status "candidate" and provenance.
- [x] Data elements by rule: a slot with a concept and a value domain gets
  the data element for that pair, created if missing.
- [x] Output: candidates with rationale, automatic matches above the
  confidence threshold, shortcut triples (`ap:dataElementConcept`,
  `ap:dataElement`).
- [x] Cache answers by fingerprint, so a rerun only asks about new slots.
- [x] Gold set, part 2 (`tests/gold-pairs.csv`): pairs of slots that should
  share a concept and pairs that should not. Concepts are created, so there
  is no fixed target to compare with; the report gives precision and recall
  on the pairs.

Done when the comparison query with `ap:dataElementConcept` returns
semantically comparable datasets on the 100-dataset sample, and a second run
creates no new entries for unchanged slots.

## Phase 4: Operation

- [x] Thresholds for automatic acceptance, set from the two gold sets.
- [x] Review queue in the run report: one row per fingerprint, ordered by the
  number of slots it covers, with the candidates and their evidence.
- [x] New datasets: a run on new input links their slots to the existing
  registry and creates entries only where nothing fits.
- [x] Reruns: automatic links are regenerated; a person's matches are
  re-attached and re-checked against the new values, and contradictions are
  flagged in the report (drift).
- [x] Registry report: entries by kind and status, entries with the most
  slots, entries with a single slot.

## Implementation (2026-11-11)

Branch `feat/concept-matching` (on `feat/ap-vocabulary`), not pushed; `pipelines/concept-matching/`,
package `cmatch`, 20 tests. Run on the 100-dataset sample: 4,525 slots, 2,813 fingerprints, 115,718
triples, valid.

- **Phase 1:** 728 code-list value domains (339 lists, 389 versions) and 7 identifier value domains
  (AHV, UID, E-GRID, EGID, EWID, EDID, postcode) in `registry/valuedomains.jsonl`; 509,213 codes in
  `cache/codes.duckdb`, refreshed per list in 18 s. A wrapper whose scheme vanishes from LINDAS is
  marked Deprecated, never removed. Done criterion checked 2026-11-11 on a local visoto-qlever: the
  graph loads (Graph Store PUT), visoto renders `…/mds/valuedomain/DV_KT_BEZ_GDE_SNAP` with its
  `mdr:permissibleValues` link to LINDAS, and that value domain joins 16 slots of 8 datasets.
- **Phase 2:** 22 automatic code-list links, 11 identifiers, 4,212 described value domains (33 rule
  value domains); 280 slots without (nested, no datatype). Two guards beyond the plan: levels that are
  dense integer ranges (AGE_HOURS 0–1200, MS regions) and value ranges where nearly every integer is a
  code (`range-overlap`, e.g. record numbers 1–60 against municipalities) are never linked
  automatically. Confirmations: re-attach, unplaced/ambiguous report, `confirmed-elsewhere`, drift.
- **Phase 3:** run for real on 2026-11-11, in a Claude Code session (answers/batch-01…10.jsonl,
  model `claude-code-session`, written through the `answers` model; hosted use approved by the user).
  All 2,813 fingerprints answered: 2,582 slots got a data element concept, 2,531 a data element; the
  registry holds 156 object classes, 882 properties, 1,297 concepts, 911 data elements, all with
  status candidate. Answers of confidence below 0.8 stay candidates. A rerun leaves the registry byte
  for byte unchanged (provenance keeps the first run). The model's code-list choices, checked
  against the values, raised gold-value recall from 0.62 to 0.88 at precision 1.00; gold pairs:
  precision 1.00, recall 0.43. `CONCEPT_MODEL=claude` (Messages API) is built but has not been
  called; it needs an API key.
- **Done criteria, checked on the local visoto-qlever:** the comparison through a shared code-list
  value domain finds, for a Thurgau dataset, six datasets on the municipality list; through a shared
  data element concept, a Zug dataset reaches two others (16 and 13 slots). The plan's query with
  `ap:valueDomain/dcterms:isVersionOf?` over all value domains exceeds QLever's query memory (rule
  value domains such as `string` join thousands of slots); restricted to enumerated value domains
  and written bottom-up (dataset's value domains in a subquery, then a UNION over list and version)
  it answers at once.
- **Phase 4:** thresholds set with `python -m cmatch tune` from the gold set (containment 0.98,
  6 distinct values, lead 0.1: precision 1.00, recall 0.62 on the draft set); review queue, drift and
  registry report in `out/report.md`.
- **Gold sets are a draft** labelled by Claude Code (`tests/GOLD.md`): 131 slots, 17 pairs. The pairs
  set measures nothing until concepts exist.

## Phase 3b: Object class per column in its table (2026-11-14)

Status: planned, nothing implemented. Revises phase 3 after a review of the
run on the 100-dataset sample.

### Why

The model is right as it is: every slot gets its own data element, so a
denormalised table can carry several object classes. The implementation
assumed normalised tables in three places, and the model saw too little of
the table to decide.

| Finding on the 100-dataset sample | Number |
|---|---|
| Fingerprints whose slots sit in more than one table | 423 of 1,559 with a concept |
| Their slots; of these, object class differs from the table's majority | 1,446; 208 (upper bound, includes real denormalisation) |
| `geom` columns without a value sample sharing one answer, "geometry (Agglomeration programme measure)" | 50 slots in 21 datasets (land-use plans, groundwater, farms, addresses) |
| Tables with concepts; with more than one object class | 463; 158 |
| Fingerprints in a table named `main` or unnamed | 743 of 2,813 |
| Neighbouring column names the model sees per slot | 5 |
| Dataset fields read by auto-profiling's `resolve` | none (distribution fields only) |
| Value-domain links that land on the generic `described/string` ("Text") | 2,706 of 4,245 |
| Slots linked to a code list or identifier | 64 of 4,525 |
| What the code index holds per code | the notation only: `BE` matches the canton list, "Bern" does not |

Causes:

- The prompt (`cmatch/concepts.py`) and [02-model.md](02-model.md#concepts)
  say the object class is the kind of thing a record of the table describes,
  and that the slots of one container normally share it.
- Answers are cached per fingerprint (name, datatype, value sample). The
  object class depends on the table, which is not in the fingerprint.
- The model sees one column, five neighbouring names and the container
  label. It sees no dependencies and nothing about the dataset.

Two gaps on the value-domain side are closed in the same revision, because
"which datasets use X, whatever its representation" depends on them:

- A string column gets the value domain "Text" whatever its values look
  like, so columns with the same shape of identifier or in-house code never
  meet.
- A data owner may publish a code, its label, or both. Only codes are
  matched today.

### The rule

A column's object class is the entity whose key determines the column.

- A key that points to another entity belongs to the **referencing** entity:
  `wohngemeinde_bfs` in a table of persons is Person + "municipality of
  residence".
- Columns that depend on that key belong to the **referenced** entity:
  `gemeinde_name` next to it is Municipality + "name".
- Columns that depend only on the row key belong to the table's own entity.

### Tasks

Auto-profiling (`pipelines/auto-profiling/`):

- [x] `resolve`: read the dataset's title, description, keywords and themes
  (`dct:title`, `dct:description`, `dcat:keyword`, `dcat:theme`). One
  language per dataset; description cut at 500 characters.
- [x] `profile`: functional dependencies per container, from the sample.
  Single-column determinants only (`bfs_nr → gemeinde_name`), each with its
  support (rows, distinct determinant values). A column that is unique per
  row is recorded as a candidate row key instead. Tabular and geo engines
  first. Dependencies from a sample are evidence, not proof: none are
  reported below a minimum number of rows.
- [x] `profile`: a pattern per string slot, from the value sample: the shape
  of the values as a regular expression (`^CH\d{12}$`, `^[A-Z]{2}$`),
  reported only when one shape covers nearly all values.
- [x] `emit`: `slots.jsonl` carries, once per container and not on every
  slot, the dataset context, the title of the representative distribution
  (already fetched, not passed on today), the full list of column names with
  datatypes, and the dependencies; per slot, its pattern. In the graph,
  dependencies become `ap:FunctionalDependency` and patterns `ap:pattern` on
  the observation (both terms exist in the `ap:` vocabulary, neither is
  emitted today).

Auto-profiling results (2026-11-16, 100-dataset sample, re-profiled offline):

- Dataset context for all 100 datasets, every language kept (decided
  2026-11-16, replacing "first of de, fr, it, en"): 26 have titles in more
  than one language. It goes to a new `out/containers.jsonl` (one line per
  container) rather than onto every line of `slots.jsonl`.
- Dependencies: 498 in 86 of 584 containers (tabular and geo); 141
  containers have a candidate key. In the municipal-finance table (Thurgau)
  `bfs_nr_gemeinde ↔ gemeinde_name` and nothing else; in the emissions table
  municipality → district. Thresholds: 50 rows, 3 determinant values
  repeating twice on average; below 50 rows the sample gave mostly noise
  (`datum → gemeinde_bfs`). Rules in
  [auto-profiling/02-model.md](../auto-profiling/02-model.md#candidate-keys-and-functional-dependencies).
- Patterns: 395 of 2,416 string slots with a sample; most are digit-only
  (`^\d{4}$` 33), which the tightened rule below keeps as "Text".
- New `ap:` terms (metadata-swiss `49d3436`): `ap:candidateKey`,
  `ap:supportRows`, `ap:determinantValues`. The output validates.
- Fingerprints are unchanged except for 6 RDF slots whose datatype flips
  between none and `xsd:string` from run to run (an older nondeterminism in
  the RDF engine).

Concept matching (`pipelines/concept-matching/`):

- [x] Write [the rule](#the-rule) into the prompt and into
  [02-model.md](02-model.md#concepts), replacing "the slots of one container
  normally share their object class". `ap:mainObjectClass` becomes the
  object class of the columns that depend on the row key (today: the
  majority of the container's slots).
- [x] Request: the model sees the whole table (all columns, dependencies,
  dataset context, distribution title) and gives one answer per column.
- [x] Cache: property and code-list choice stay keyed by fingerprint. The
  object class is keyed by fingerprint plus table (dataset and container
  name, as in the re-attach key). Dataset context is not part of any key, so
  an edited description causes no new call.
- [x] Existing answers: properties are kept, object classes are asked again
  under the rule.
- [x] Tests: a denormalised table gets two object classes (person with
  `wohngemeinde_bfs` and `gemeinde_name`); two tables sharing a `geom`
  fingerprint get different object classes; a changed dataset description
  makes no model call.

Value domains (`pipelines/concept-matching/`, stages `codes` and
`link-values`, no LLM):

- [x] Patterns: the rule for described value domains uses the slot's pattern
  for strings, so two string columns with the same specific shape reach the
  same entry and free text stays "Text".
- [x] Labels and codes: the code index also holds each code's labels
  (`skos:prefLabel`, all languages). A slot's values are compared with the
  notations and with the labels, normalised for case, accents and
  whitespace. A column of codes and a column of labels of the same list link
  to the same value domain; the evidence records what matched (notation or
  label, and the language).
- [x] The rules for an automatic link (containment, distinct values, lead
  over the next list) apply to label matches as well. Generic labels ("Ja",
  "Nein", "Total", "Andere") occur in many lists and must not link on their
  own.
- [x] Vocabulary (`metadata-swiss`): a term on `ap:Evidence` for what
  matched.
- [x] Gold set: cases with labels, and with a code column and a label column
  of the same list in one table.

Done when, on the 100-dataset sample: no `geom` column carries the object
class of another table's entity; in the municipal-finance table
`gemeinde_name` is Municipality + "name" while the finance ratios keep the
table's own object class; a rerun with an edited dataset description makes
no model call; a column of canton names and a column of canton
abbreviations link to the same value domain; and the report shows pattern
value domains shared by more than one dataset.

### Choices made while writing, to confirm

- **Language of the dataset context:** all languages (decided 2026-11-16).
- **Unit of a model call:** the table (confirmed 2026-11-14). All its
  columns that lack an answer are asked together, with the full column list
  as context. Today it is one call per fingerprint.
- **Dependencies:** single-column determinants only, no composite keys.
- **Concept registry:** reset once for this revision (confirmed
  2026-11-14; still the experimentation phase, nothing is published). The
  object classes, concepts and data elements of the first run are discarded
  and created again by the phase 3b rerun; properties and value domains are
  kept. This is a single exception: the registry is state and is not rebuilt
  on a normal run. Still to confirm: from the first load into a shared graph
  on, an entry is never removed, only marked Deprecated with a pointer to
  its replacement.
- **Codes and labels share one value domain.** Both link to the code list's
  entry and the link says what matched. Strictly by ISO/IEC 11179 they are
  two value domains of one conceptual domain; that level does not exist in
  `mdr:` and is still undecided (below).
- **When a pattern is specific enough** to make its own value domain
  (decided 2026-11-16): the shape has at least one fixed literal character,
  a prefix (`CHE-`, `A-`) or a separator (`.`, `/`, `-`). `^A\-\d{4}$`
  qualifies; `^\d{4}$` and `^[A-Z]{2}$` stay "Text" (letters-only and
  digit-only shapes join unrelated codes; code lists and identifier rules
  catch the meaningful ones first). A space is not a separator.

### Not covered here

Raised in the same review and still undecided: a level above the value
domain (one entry for "municipality" whatever its representation), a real
embedding model for the lookup, a run of the `claude` model path, and a gold
set labelled by a person.

## Later

- **Pruning:** merging duplicate concepts, object classes and properties in
  the knowledge graph; the replaced entry points to its replacement and the
  links follow.
- A review UI in visoto that writes a person's matches to the confirmations
  graph, replacing `confirmations.csv`.
- Converting datasets to RDF: target shapes, RML (triples maps, sentinels),
  conversion and validation of the converted data.
- Superset structures: one structure for slightly diverging distributions.
- Value histograms in auto-profiling (functional dependencies and patterns
  moved to [phase 3b](#phase-3b-object-class-per-column-in-its-table-2026-11-14)).
