# Publish: Turtle on GitHub

The pipeline does not write to QLever. It publishes its Turtle to GitHub, and
visoto pulls it from there into its private QLever. Visoto never accepts
inbound writes, so there is no access token, SSH tunnel or deploy key to
manage.

## Where

One **GitHub Release per pipeline** with a fixed tag, replaced on every run:

```
https://github.com/pdacton/visoto-pipelines/releases/download/i14y-latest/i14y.ttl
```

- A stable URL visoto can fetch without knowing about runs. The repo is
  public, so the download needs no GitHub token.
- Release assets are not part of git history, so nightly full refreshes don't
  bloat the repo (and avoid the 100 MB file limit).
- The workflow uses the built-in `GITHUB_TOKEN`; no extra secrets.
- Alongside the Turtle, publish `i14y.meta.json` (run time, commit, triple
  count, source record counts) for checking a run before loading it.

## Graph IRI

Each pipeline owns one named graph, `urn:data:<name>-githubpipeline`; for this
one `urn:data:i14y-githubpipeline`. The suffix marks data produced by this
repo, as opposed to manual uploads (`urn:visoto:graph:…`).

## Visoto side

Loading is triggered **manually**, with visoto's existing upload:

- In the upload modal's **URL** tab, paste the release URL and set the graph
  IRI to `urn:data:i14y-githubpipeline` (the tab proposes a
  `urn:visoto:graph:…` name, which must be overwritten).
- Visoto's upload `POST`s to the graph, which **adds** triples. A refresh is
  therefore: delete the graph in visoto, then load it again. Without the
  delete, blank nodes would be duplicated on every load.
- Visoto writes the graph metadata (`rdfs:label`, `dcterms:modified`) itself.
