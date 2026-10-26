# Open questions

- **Is I14Y already on LINDAS?** Its IRIs use `register.ld.admin.ch/i14y/...`.
  Queries against LINDAS timed out on 2026-10-26. If it is there, compare
  coverage and freshness before building the full pipeline.
- **QLever `PUT` support** for the Graph Store protocol — verify, else
  `DROP` + `POST`.
- **QLever port and SSH user** on the visoto host for the tunnel.
- **Named graph IRI** scheme for pipeline graphs.
- **SPARQL Anything vs Python** — decided after the evaluation in
  [03-transform.md](03-transform.md).
