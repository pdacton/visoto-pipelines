# Orchestration: GitHub Actions

- One workflow per pipeline, triggered by a nightly `schedule` and by
  `workflow_dispatch`.
- Jobs: fetch → transform → validate (SHACL) → load. The Turtle output is
  uploaded as a workflow artifact before loading, so every load can be
  inspected or replayed.
- A failed validation stops the run before anything is written to QLever.
- Everything a workflow runs is a script in the repo, so it also runs locally.
