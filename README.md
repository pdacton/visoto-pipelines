# visoto-pipelines

Pipelines that turn external sources into RDF for
[visoto](https://github.com/pdacton/visoto). Each pipeline publishes one
Turtle file as a GitHub Release (`<name>-latest`); visoto loads it through
the upload modal's URL tab into the named graph `urn:data:<name>-githubpipeline`.

| Pipeline | Turtle | Plan |
|---|---|---|
| I14Y | [i14y.ttl](https://github.com/pdacton/visoto-pipelines/releases/download/i14y-latest/i14y.ttl) | [.project/i14y](.project/i14y) |

## Run locally

Needs `bash`, `curl` and Java 21+ (or a JRE unpacked into `.tools/`). SPARQL
Anything, Jena and jq are downloaded into `.tools/` on first use.

```sh
scripts/run.sh i14y               # fetch → transform → validate → meta
scripts/run.sh i14y --skip-fetch  # rerun from the saved raw/
scripts/publish.sh i14y           # replace the release assets (needs gh auth)
```

Output: `pipelines/i14y/out/i14y.ttl` and `i14y.meta.json`.

## Adding a pipeline

Create `pipelines/<name>/` with `pipeline.env`, `fetch.sh`, `queries/*.sparql`
and `shapes.ttl` (optionally `checks/*.rq`), and a workflow that calls
`pipeline.yml` with `name: <name>`. See [.project/i14y/01-purpose.md](.project/i14y/01-purpose.md).
