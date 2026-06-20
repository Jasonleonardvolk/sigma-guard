# MCP Registry Submission Metadata
# Use this metadata when submitting to MCP registries.
# Last updated: May 27, 2026

## Server metadata

- **Name:** sigma-guard
- **Display name:** SIGMA Guard
- **One-line description:** Deterministic structural contradiction detection for knowledge graphs, agent state, and LLM output using sheaf cohomology. Returns deterministic proof receipts. Zero ML.
- **Category:** Data Science & ML / Developer Tools / Quality Assurance
- **Tool count:** 3
- **Transport types:** stdio, Streamable HTTP
- **Protocol version:** 2025-03-26+
- **License:** BSL-1.1 (free tier: 10K vertices / 100K edges)
- **Homepage:** https://invariant.pro
- **Repository:** https://github.com/Jasonleonardvolk/sigma-guard
- **Documentation:** https://invariant.pro/docs/sigma-guard/mcp
- **Author:** Jason Volk (jason@invariant.pro)
- **Organization:** Invariant Research
- **Install:** pip install sigma-guard[mcp]
- **Run (stdio):** sigma-guard-mcp
- **Run (HTTP):** sigma-guard-mcp --transport streamable-http --port 8401
- **MCP endpoint:** /mcp (for Streamable HTTP)

## Tools exposed

1. **verify_graph** - Detect structural contradictions in knowledge graphs, agent memory, and compliance graphs using cellular sheaf cohomology.
2. **verify_claims** - Verify LLM output claims for structural consistency. Catches hallucinations before emission.
3. **check_write** - Pre-commit gate: check if a proposed graph mutation would create a contradiction.

## Key differentiators (for registry descriptions)

- Deterministic: same input always produces same output
- Zero ML, zero GPU, zero training data
- 35 microseconds per edit at 5M vertices
- Content-addressed proof receipt on every verdict
- Model-agnostic: works with any LLM or agent framework
- Catches contradictions that schema validation misses

## Registry-specific submission notes

### mcp.so
Submit via: https://mcp.so (submit button or contact form)
Key fields: name, description, GitHub URL, install command

### smithery.ai
Submit via: `smithery mcp publish` CLI or PR to community-servers repo
Steps:
  1. Create account at smithery.ai
  2. `smithery auth login`
  3. `smithery mcp publish "https://your-server/mcp" -n invariant-research/sigma-guard`
  Or: PR to https://github.com/smithery-ai/community-servers-1

### glama.ai
Submit via: https://glama.ai/mcp (submit form)
Key fields: name, description, GitHub URL, category

### punkpeye/awesome-mcp-servers (GitHub)
Submit via: PR to https://github.com/punkpeye/awesome-mcp-servers
Format: add entry to README with name, description, link

### GitHub MCP Registry
Submit via: PR or registration at https://github.com/modelcontextprotocol/servers
Follow their contribution guidelines

## Submission checklist

- [ ] GitHub repo is public with clean README
- [ ] pip install sigma-guard[mcp] works from PyPI
- [ ] sigma-guard-mcp runs without errors (stdio)
- [ ] sigma-guard-mcp --transport streamable-http runs
- [ ] Submit to mcp.so
- [ ] Submit to smithery.ai
- [ ] Submit to glama.ai/mcp
- [ ] PR to punkpeye/awesome-mcp-servers
- [ ] Submit to GitHub MCP Registry
- [ ] Verify listings appear and descriptions are correct
