# Open questions

- **LLM:** which model, the cost of a full run (about 300k slots, roughly a
  third as many fingerprints), and whether sample values may be sent to a
  hosted API (possible personal data, the same concern as auto-profiling's
  example values).
- **Embedding model:** multilingual (de/fr/it/en), local or hosted.
- **Value sample:** about 200 random distinct values per slot, or all values
  up to a cap such as 5,000.
- **Thresholds:** minimum containment and number of distinct values for an
  automatic code-list link, the confidence above which an LLM decision is
  accepted without review, and the precision targets (proposed: 0.9); set
  once the gold set exists.
- **Language of created entries:** labels and definitions in English only, or
  in de/fr/it/en.
- **Technical columns:** whether columns such as `objectid` or `gml_id` get a
  concept ("record identifier") or none.
- **Rule-made value domains:** how fine the rules cut (is "integer, year" one
  value domain or is every range its own).
- **Labels instead of codes:** columns that hold "Bern" instead of `BE` need
  matching on `skos:prefLabel` per language.
- **Confirmations graph:** its name, and how the review UI will write it
  later (visoto's `/api/sparql` proxy has a write allowlist).
- **Registry in the repo:** whether LLM-created entries may live in the
  public `visoto-pipelines` repo, or need a private one.
