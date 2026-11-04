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
- **PxWeb tables per language:** Liechtenstein publishes one table per
  language under different names (`251.501d`, `251.501e`); they are profiled
  as separate structures. BFS tables in several languages are one structure
  with labels per language.
- **Opendatasoft RDF exports:** profiled as their own structure (classes and
  predicates of the publisher's RDF model), next to the table structure of the
  other exports. Decide whether visoto should show both.
- **WFS coverage:** only the first `WFS_MAX_LAYERS` layers of a service are
  sampled; services such as `geo.ur.ch` list several hundred.
- **Output size:** every observed value list and example is in the graph;
  watch the size in visoto-qlever before running on all ~35,500
  distributions.
