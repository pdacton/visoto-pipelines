# Gold sets

**Draft.** Labelled by Claude Code on 2026-11-11 from column names and value samples of the
100-dataset sample (`datasets-sample.txt`); review before setting thresholds from them.

- `gold-values.csv`: 131 slots drawn by stratum (40 with an automatic code-list or identifier link,
  60 with code-list candidates, the rest other slots with values), one per fingerprint, keyed by the
  re-attach key. `expected` is a registry identifier (a code list counts with all its versions, or
  `identifier/<name>`), `described` (only the rule-made value domain) or `none`.
  Added 2026-11-16 (phase 3b): 12 label cases, among them tables with a code column and a label
  column of the same list (`entity_id`/`entity_name`, `bfs_nr_gemeinde`/`gemeinde_name`,
  `cantonabbreviation`/`cantonname`) and yes/no columns that must stay `described`.
- `gold-pairs.csv`: pairs of slots that should (`same` 1) or should not (0) share a data element
  concept. Derived from gold-values; still small.

The report (`out/report.md`, section "Gold sets") gives precision and recall on both.
