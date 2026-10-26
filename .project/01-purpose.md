# Purpose

Data pipelines that turn external sources into RDF and load them into
visoto's private QLever triplestore, so visoto can render them.

- Visoto (`github.com/pdacton/visoto`) renders RDF from SPARQL endpoints and
  has no database of its own. This repo is the only producer of data for its
  private QLever endpoint (slug `visoto-qlever`).
- Each pipeline owns **one named graph** and replaces it in full on every run.
  No incremental updates, so a run is idempotent and a broken run is fixed by
  the next good one.
- Visoto needs no code change to show new data; at most it gets new class or
  instance templates.

## Shape of a pipeline

```
pipelines/<name>/
  fetch.sh            # extract: source → raw/*.json
  queries/*.sparql    # transform: one CONSTRUCT per resource type
  shapes.ttl          # validate: SHACL
scripts/load-qlever.sh  # load: shared by all pipelines
.github/workflows/<name>.yml
```

Extract → transform → validate → load. Each step reads files written by the
previous one, so any step can be rerun locally on its own.
