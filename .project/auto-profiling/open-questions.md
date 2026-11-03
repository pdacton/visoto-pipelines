# Open questions

- **`BASE_IRI` for production:** it defaults to `https://example.org/auto-profiling/`.
  Decide on `visoto.hutzli.org` or `ld.admin.ch` before structures are shared
  beyond visoto. Changing it later changes every IRI.
- **`prof:` vocabulary:** whether a small custom vocabulary is acceptable
  long-term, or whether the statistics should map to DQV or an existing
  profiling vocabulary.
- **Equivalence groups:** treating Opendatasoft exports of one dataset as one
  structure is a heuristic, based on the same dataset and the same export base
  path. Check that it never merges genuinely different tables.
- **Example values:** distributions are public data, but sample values could
  still contain personal data (registers, lists). Keep at most 3 examples per
  field, truncated, and decide whether to drop examples for free-text fields.
- **Shared dimensions and I14Y concepts:** linking codes (cantons, BFS
  municipality numbers) to LINDAS or I14Y IRIs is the main interoperability
  step. It is deliberately out of scope here.
- **Scheduling:** whether to add a GitHub Actions workflow once the network
  constraints are understood. It runs locally for now.
