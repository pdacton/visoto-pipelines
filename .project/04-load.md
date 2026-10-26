# Load: Graph Store protocol → private QLever

- Write with the **SPARQL 1.1 Graph Store HTTP protocol**, the same mechanism
  visoto's own upload uses (`POST <qlever>?graph=<iri>` with
  `Authorization: Bearer $QLEVER_ACCESS_TOKEN`).
- Full refresh per run: `PUT ?graph=<iri>` replaces the graph. If QLever
  rejects `PUT`, use `DROP GRAPH <iri>` (SPARQL Update) followed by `POST`.
- After loading, write the graph metadata visoto shows on uploads
  (`rdfs:label`, `dcterms:modified` on the graph IRI).

## Reachability

QLever sits on the Docker-internal `qlever-private` network on the visoto
host; neither Caddy nor the internet can reach it, and that stays so.

The Actions runner reaches it through an **SSH tunnel** to the host
(`ssh -L 7019:qlever:7019`, port to be confirmed) and speaks the Graph Store
protocol through the tunnel. No new public route, no self-hosted runner.

Secrets (repo settings): `QLEVER_ACCESS_TOKEN`, SSH deploy key, host, known_hosts.

## Graph IRIs

One named graph per pipeline, e.g. `https://visoto.hutzli.org/graph/i14y`
(to be fixed in open questions).
