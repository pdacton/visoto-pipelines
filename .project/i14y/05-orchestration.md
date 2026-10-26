# Orchestration: GitHub Actions

- `.github/workflows/pipeline.yml` is reusable: checkout → Java 21 → cached
  tools → `scripts/run.sh <name>` (fetch, transform, validate, meta) →
  `scripts/publish.sh <name>`.
- `.github/workflows/i14y.yml` calls it nightly and on `workflow_dispatch`.
- A failed validation stops the run before anything is published, so the
  previous good Turtle stays in place. The failed run's `raw/` and `out/` are
  kept as a workflow artifact for 7 days.
- Everything a workflow runs is a script in the repo, so it also runs locally.
- Tool versions (SPARQL Anything 1.2.0, Jena 6.2.0) are pinned in
  `scripts/lib.sh` and downloaded into `.tools/`.
