# Orchestration: GitHub Actions

- One workflow per pipeline, triggered by a nightly `schedule` and by
  `workflow_dispatch`.
- Jobs: fetch → transform → validate (SHACL) → publish. Publish replaces the
  pipeline's `<name>-latest` release assets (see [04-publish.md](04-publish.md)).
- A failed validation stops the run before anything is published, so the
  previous good Turtle stays in place.
- Everything a workflow runs is a script in the repo, so it also runs locally.
