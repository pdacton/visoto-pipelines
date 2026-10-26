# Purpose

Data pipelines that turn external sources into RDF and publish it as Turtle
on GitHub, from where visoto loads it into its private QLever triplestore.

- Visoto (`github.com/pdacton/visoto`) renders RDF from SPARQL endpoints and
  has no database of its own. Its private QLever endpoint (slug
  `visoto-qlever`) holds manual uploads and the graphs published here.
- Visoto pulls the published Turtle with its existing upload-from-URL, so
  nothing here needs credentials for the visoto host.
- Each pipeline produces **one named graph** and publishes it in full on every
  run. No incremental updates, so a run is idempotent and a broken run is fixed
  by the next good one.
- Visoto needs no code change to show new data; at most it gets new class or
  instance templates.

## Repo layout

```
pipelines/<name>/
  fetch.sh            # extract: API → raw/*.json, LINDAS → raw/*.ttl
  lindas/*.sparql     # extract: CONSTRUCT queries run against LINDAS
  queries/*.sparql    # transform: SPARQL Anything mappings
  shapes.ttl          # validate: SHACL
  pipeline.env        # name, graph IRI, release tag, endpoints
  raw/  out/          # gitignored
scripts/              # shared by all pipelines
  run.sh <name>       # fetch → transform → validate, locally and in CI
  sparql-anything.sh  # fetches the pinned jar, runs a query
  lindas-construct.sh # paged CONSTRUCT against a SPARQL endpoint
  validate.sh         # SHACL + sanity checks
  publish.sh          # replaces the <name>-latest release assets
.github/workflows/
  pipeline.yml        # reusable workflow (workflow_call, input: name)
  <name>.yml          # schedule + dispatch, calls pipeline.yml
.project/<name>/      # plan per pipeline
```

Extract → transform → validate → publish. Each step reads files written by the
previous one, so any step can be rerun locally on its own. A new pipeline is a
new `pipelines/<name>/` folder plus a short workflow file.
