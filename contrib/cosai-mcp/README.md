# Proposed contributions to cosai-mcp

These files are proposed contributions to the
[cosai-mcp](https://github.com/ragsvasan/cosai-mcp) project. Each file
is self-contained and can be submitted as an individual PR.

## Catalog probes

**T09-001.json** -- Totem violation check (HIGH severity). Checks whether
MCP server tool definitions include two-stage commit patterns for
destructive operations. Implements the T9 Totem check described in
THREAT_CATALOG.md. The probe uses regex on the tools/list response to
detect confirmation/dry-run parameters. Full structural analysis (parsing
tool definitions, matching destructive verbs against parameter schemas)
requires a code contribution to the scanner.

**T09-002.json** -- SVR receipt presence check (INFO severity). Checks
whether MCP server tool descriptions reference structural verification
or SVR receipts. Informational: absence is not a vulnerability but
indicates no deterministic verification gate is present at the T9
trust boundary.

## Code contributions

**check_resource_read.py** -- Closes the resources/read audit gap
identified in THREAT_CATALOG.md. Adds a check_resource_read() method to
CoSAIStack that logs resources/read events to the AuditLogger with DAG
parent_id linkage. Includes two test cases.

**verified_output_profile.py** -- Security profile for MCP servers that
produce SVR receipts. Seeds sigma-guard tool names (verify_graph,
verify_claims, check_write). No categories skipped.

**svr_chain_scenario.py** -- Stateful harness scenario testing SVR
receipt chain integrity across a multi-hop MCP pipeline. Three steps:
call verify_claims, call verify_graph (simulating downstream chaining),
re-fetch tools/list mid-session for T6 rug pull detection. Includes a
standalone runner for development/demo.

## Submission order

1. T09-001.json (Totem) -- implements existing THREAT_CATALOG.md spec
2. check_resource_read.py -- closes documented gap
3. T09-002.json (SVR receipt) -- extends catalog
4. svr_chain_scenario.py -- extends stateful harness
5. verified_output_profile.py -- extends profiles

## License

All files in this directory are offered under Apache 2.0 to match
cosai-mcp's license.

## Contact

Jason Volk / sigma-guard / SVR
jason@invariant.pro
https://invariant.pro
