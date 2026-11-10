# concept-matching

Build a registry of value domains and data element concepts in the knowledge
graph, bottom-up from the auto-profiled structures, and link every slot to
its entries. Datasets whose slots point at the same entries are comparable.

| File | Intent |
|---|---|
| [01-purpose.md](01-purpose.md) | Goal, decisions taken, scope |
| [02-model.md](02-model.md) | Registry entries, links, graphs, IRIs, matching rules |
| [03-plan.md](03-plan.md) | Implementation phases with tasks and done criteria |
| [open-questions.md](open-questions.md) | Not yet decided |

Started 2026-11-10 (design only, nothing implemented). Depends on
[auto-profiling](../auto-profiling/) and on the `ap:` and `mdr:` vocabularies
in `metadata-swiss/mds-datamodel/ontology/` (`autoprofiling/`, `dataelement/`).
