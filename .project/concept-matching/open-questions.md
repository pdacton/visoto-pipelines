# Open questions

- **Where the matcher lives:** a new `concept-matching` pipeline with its own
  graph, reading auto-profiling's `out/profiles/*.json` and pointing at its
  slot IRIs (reruns independent of profiling), or a stage inside
  auto-profiling. Leaning towards a separate pipeline.
- **Scoring thresholds:** minimum containment and how coverage weighs in;
  set after the phase 2 test set exists.
- **Identity vs version:** LINDAS lists terms under both the version and the
  identity IRI of a scheme. Wrap only versions, and link identities through
  `version.link`?
- **Load on LINDAS:** number and size of `VALUES` queries for ~28k fields;
  cache results by value-set hash.
- **Label normalisation:** codes published as labels ("Bern" instead of
  `BE`) need matching on `skos:prefLabel` per language too.
- **Data element concepts:** no source yet. Candidates from I14Y concept
  names, or wait for manually registered concepts?
- **Overlap of test datasets:** how many of the I14Y datasets behind the 657
  shapes have downloadable opendata.swiss distributions.
