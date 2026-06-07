# Changelog

## v0.3.1 (2026-06-07)

### Features

- Standalone verifier: pure numpy/scipy sheaf cohomology verification
  with no engine dependency. Apache 2.0 licensed.
- MCP server: Model Context Protocol integration for agent-based
  verification workflows. Install with `pip install sigma-guard[mcp]`.
- Graph database adapters: Memgraph (before-commit hook), Neo4j
  (guarded write wrapper), FalkorDB (adapter base).
- CLI tools: `sigma-guard` for graph verification, `sigma-verify`
  for standalone mode, `sigma-guard-mcp` for MCP server.
- Docker support: `docker run jasonvolk/sigma-guard demo supply_chain`
  for zero-install demos.
- CI integration: exit code 0 (consistent), 1 (contradiction), 2 (error).
- Four bundled datasets with planted contradictions and ground truth:
  supply chain, cybersecurity, knowledge graph, and tiny contradiction.
- Bring-your-own-graph: JSON, GraphML, and edge-list parsers.
- Proof receipt schema with deterministic proof IDs.
- Dirichlet energy localization: contradictions reported with exact
  edge locations and severity levels (CRITICAL/HIGH/MODERATE/LOW).

### Performance (Full SIGMA Engine)

- 5M vertices validated
- 35 microseconds median per-edit latency
- Sub-linear scaling exponent (0.19)
- Zero drift (measured via full recompute, not assigned)
- No ML, no GPU required

### Dependencies

- Python >= 3.9
- numpy >= 1.21
- scipy >= 1.7
- Optional: mcp, gqlalchemy, neo4j, falkordb

### License

- Standalone verifier: Apache 2.0
- Full package: BSL-1.1 with free tier (10K vertices / 100K edges)
