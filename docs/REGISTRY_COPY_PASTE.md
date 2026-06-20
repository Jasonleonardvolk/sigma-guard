# Registry Submission Copy
# Ready-to-paste text for each registry. Just open the links and paste.

# ============================================================
# 1. mcp.so
# ============================================================
# URL: https://mcp.so (look for "Submit" or "Add Server")
#
# Name: sigma-guard
# Description (paste this):

Deterministic structural contradiction detection for knowledge graphs,
agent state, and LLM output. Uses cellular sheaf cohomology (H^1) to
find contradictions that schema validation and constraint engines miss.
Three tools: verify_graph (audit a knowledge graph), verify_claims
(check LLM output before emission), check_write (pre-commit gate for
graph mutations). Returns deterministic proof receipts. Zero ML, zero
GPU, 35 microseconds per edit at 5M vertices. Model-agnostic.

# GitHub: https://github.com/Jasonleonardvolk/sigma-guard
# Homepage: https://invariant.pro
# Install: pip install sigma-guard[mcp]
# Transport: stdio, Streamable HTTP
# Category: Developer Tools / Data Science & ML


# ============================================================
# 2. smithery.ai
# ============================================================
# Option A: CLI submission
# Run these commands:
#
#   npm install -g @smithery/cli
#   smithery auth login
#   smithery mcp publish "https://invariant.pro/mcp" -n jasonlvolk/sigma-guard
#
# Option B: PR to community-servers repo
# Fork: https://github.com/smithery-ai/community-servers-1
# Add this entry to the README:

### sigma-guard
Deterministic structural contradiction detection for knowledge graphs,
agent state, and LLM output using sheaf cohomology. Verify graphs,
check LLM claims, gate graph mutations. Deterministic proof receipts.
Zero ML.

- **Install:** `pip install sigma-guard[mcp]`
- **Run:** `sigma-guard-mcp`
- **Transport:** stdio, Streamable HTTP
- **Repository:** https://github.com/Jasonleonardvolk/sigma-guard
- **Homepage:** https://invariant.pro


# ============================================================
# 3. glama.ai/mcp
# ============================================================
# URL: https://glama.ai/mcp (look for submit/add)
#
# Name: sigma-guard
# Description (paste this):

Deterministic structural contradiction detection for knowledge graphs,
agent state, and LLM output. Uses sheaf cohomology to catch
contradictions that schema validation misses. Tools: verify_graph,
verify_claims, check_write. Deterministic proof receipts. Zero ML.
35us per edit at 5M vertices.

# GitHub: https://github.com/Jasonleonardvolk/sigma-guard
# Homepage: https://invariant.pro
# Category: Data Science & ML


# ============================================================
# 4. punkpeye/awesome-mcp-servers (GitHub PR)
# ============================================================
# Fork: https://github.com/punkpeye/awesome-mcp-servers
# Find the appropriate category section and add this line:

- [sigma-guard](https://github.com/Jasonleonardvolk/sigma-guard) - Deterministic structural contradiction detection for knowledge graphs and LLM output using sheaf cohomology. Verify graphs, check claims, gate mutations. Deterministic proofs. Zero ML.

# PR title: Add sigma-guard: deterministic structural verification for graphs and LLM output
# PR body:

Adds sigma-guard, a deterministic structural verification server for
knowledge graphs, agent state, and LLM output.

Tools exposed:
- verify_graph: detect contradictions in knowledge graphs
- verify_claims: verify LLM output claims before emission
- check_write: pre-commit gate for graph mutations

Uses cellular sheaf cohomology (H^1). Returns deterministic proof
receipts. Zero ML, zero GPU. 35 microseconds per edit at 5M vertices.
Supports stdio and Streamable HTTP transports.

Install: pip install sigma-guard[mcp]
Homepage: https://invariant.pro


# ============================================================
# 5. GitHub MCP Registry (modelcontextprotocol/servers)
# ============================================================
# Fork: https://github.com/modelcontextprotocol/servers
# Follow their contribution guidelines for adding a community server.
# PR title: Add sigma-guard: structural verification for graphs and LLM output
# PR body (same as #4 above, adjust to their template if they have one)


# ============================================================
# AFTER ALL SUBMISSIONS
# ============================================================
# Verify each listing by searching for "sigma-guard" on each registry.
# Update docs/REGISTRY_SUBMISSION.md checklist as you go.
# Once all 5 are confirmed, add the registry links to the README.md
# MCP section and docs/mcp_server.md registry section.
