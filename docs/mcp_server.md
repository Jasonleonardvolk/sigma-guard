# MCP Server Integration

SIGMA Guard runs as an MCP (Model Context Protocol) server, exposing
deterministic graph verification as tools that any MCP-compatible
agent can call. Supports both local (stdio) and remote (Streamable
HTTP) transports per MCP spec 2025-03-26+.

## Install

```
pip install sigma-guard[mcp]
```

Requires `mcp>=1.6` (FastMCP with Streamable HTTP support).

## Run

```bash
# stdio transport (default -- Claude Desktop, Cursor, Claude Code)
sigma-guard-mcp

# Streamable HTTP transport (remote agents, production deployment)
sigma-guard-mcp --transport streamable-http --port 8401

# Custom host binding
sigma-guard-mcp --transport streamable-http --host 0.0.0.0 --port 8401
```

The Streamable HTTP server exposes a single endpoint at `/mcp`
(e.g. `http://localhost:8401/mcp`).

## Tools

The server exposes three tools:

### verify_graph

Detect structural contradictions in a knowledge graph, agent memory
graph, compliance graph, or any graph where nodes carry claims that
must be globally consistent. Uses cellular sheaf cohomology (H^1) to
find contradictions that schema validation and constraint engines miss.

**When to call:** Before trusting retrieved graph data. After GraphRAG
retrieval. After knowledge graph ETL merges. When auditing agent memory
for accumulated contradictions ("agent debt").

**Input:** JSON graph with `vertices` (each having `id` and `claims`
as key-value pairs) and `edges` (each having `source`, `target`, and
optional `relation`).

**Output:** Deterministic verdict (CONSISTENT or INCONSISTENT), exact
contradiction locations with severity rankings, Dirichlet energy per
edge, and a content-addressed proof ID.

### verify_claims

Verify a list of claims extracted from LLM output, RAG retrieval, or
agent reasoning for structural consistency. Detects hallucinations
where an LLM asserts contradictory facts.

**When to call:** Before emitting LLM output to the user. After RAG
retrieval to check that retrieved facts agree. When an agent accumulates
state across multiple tool calls.

**Input:** List of claims, each with `subject` (entity), `property`
(attribute), and `value` (what is asserted).

**Output:** Verdict (SAFE or UNSAFE), contradiction details, and a
deterministic proof receipt. If UNSAFE, includes a recommendation to revise,
flag for human review, or block emission.

### check_write

Check whether a proposed graph mutation would create a structural
contradiction BEFORE committing the write. Acts as a pre-commit
verification gate.

**When to call:** As a write guard in GraphRAG pipelines, agent
memory systems, Memgraph/Neo4j pre-commit hooks, or any workflow
where graph mutations must preserve consistency.

**Input:** Current graph state plus proposed `source`, `target`,
and `relation` for the new edge.

**Output:** Whether the write is safe to commit or would introduce
a contradiction, with deterministic proof.

## Agent configuration

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
    "mcpServers": {
        "sigma-guard": {
            "command": "sigma-guard-mcp",
            "args": []
        }
    }
}
```

### Claude Desktop (remote via Streamable HTTP)

If running the server remotely:

```json
{
    "mcpServers": {
        "sigma-guard": {
            "type": "streamable-http",
            "url": "http://your-server:8401/mcp"
        }
    }
}
```

### Cursor

Add to `.cursor/mcp.json` in your project root:

```json
{
    "mcpServers": {
        "sigma-guard": {
            "command": "sigma-guard-mcp",
            "args": []
        }
    }
}
```

### Claude Code

```bash
claude mcp add sigma-guard sigma-guard-mcp
```

### Hermes Agent

```json
{
    "mcpServers": {
        "sigma-guard": {
            "command": "sigma-guard-mcp",
            "args": [],
            "env": {}
        }
    }
}
```

### LangChain (via langchain-mcp-adapters)

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async with MultiServerMCPClient(
    {
        "sigma-guard": {
            "url": "http://localhost:8401/mcp",
            "transport": "streamable_http",
        }
    }
) as client:
    tools = client.get_tools()
    # tools now includes verify_graph, verify_claims, check_write
    # Pass to your LangChain agent as usual
```

### Any MCP-compatible agent

The server uses standard MCP protocol (spec 2025-03-26+). Any agent
that supports MCP tool calls can connect via stdio or Streamable HTTP.

## Example: verify claims from LLM output

An agent extracts two claims from its generated answer:

```json
{
    "claims": [
        {"subject": "Component_X", "property": "ships", "value": "Q2"},
        {"subject": "Component_X", "property": "production_start", "value": "Q3"}
    ]
}
```

SIGMA responds:

```json
{
    "verdict": "UNSAFE",
    "safe_to_rely_on": false,
    "claims_checked": 2,
    "contradiction_count": 1,
    "contradictions": [
        {
            "severity": "CRITICAL",
            "location": ["Component_X", "Component_X"],
            "explanation": "disagree on: production_start, ships"
        }
    ],
    "receipt_id": "sigma:proof:...",
    "recommendation": "LLM output contains structural contradictions. Revise, flag for human review, or block emission."
}
```

The agent can then revise, flag, or block the answer.

## Example: verify graph data

An agent builds a knowledge graph from retrieved documents:

```json
{
    "graph": {
        "vertices": [
            {"id": "Policy", "claims": {"approved_vendor": "Supplier_A"}},
            {"id": "Procurement", "claims": {"approved_vendor": "Supplier_B"}}
        ],
        "edges": [
            {"source": "Policy", "target": "Procurement", "relation": "governs"}
        ]
    }
}
```

SIGMA responds:

```json
{
    "verdict": "INCONSISTENT",
    "safe_to_rely_on": false,
    "contradiction_count": 1,
    "contradictions": [
        {
            "severity": "CRITICAL",
            "location": ["Policy", "Procurement"],
            "explanation": "disagree on: approved_vendor"
        }
    ],
    "receipt_id": "sigma:proof:...",
    "deterministic": true
}
```

## Example: pre-commit write guard

An agent wants to add an edge to an existing graph:

```json
{
    "graph": {
        "vertices": [
            {"id": "X", "claims": {"approved": "yes"}},
            {"id": "Y", "claims": {"approved": "no"}}
        ],
        "edges": []
    },
    "source": "X",
    "target": "Y",
    "relation": "policy_check"
}
```

SIGMA responds:

```json
{
    "write": "X -> Y (policy_check)",
    "creates_contradiction": true,
    "safe_to_commit": false,
    "severity": "CRITICAL",
    "recommendation": "Block this write."
}
```

## Architecture

```
Any LLM (OpenAI, Anthropic, Google, Meta, Mistral, local)
        |
        v
Agent framework (Claude, LangChain, LlamaIndex, Hermes, custom)
        |
        v
MCP tool call: verify_claims or verify_graph or check_write
        |
        v
SIGMA Guard MCP Server (stdio or Streamable HTTP)
        |
        v
Sheaf cohomology verification (deterministic, zero ML)
        |
        v
Verdict + deterministic proof receipt returned to agent
        |
        v
Agent decides: emit, revise, block, or flag for human review
```

The model does not matter. The verification does.

## Transport comparison

| Transport | Use case | Latency overhead |
|---|---|---|
| stdio | Local agents (Claude Desktop, Cursor, Claude Code) | Zero network overhead |
| Streamable HTTP | Remote agents, production deployment, multi-client | 5-25ms network round-trip |
| SSE (deprecated) | Legacy clients only | Use Streamable HTTP instead |

## Performance

| Metric | Value |
|---|---|
| Per-edit latency (median) | 35 microseconds |
| Validated scale | 5,000,000 vertices |
| Cohomology drift | 0 (mathematically exact) |
| ML required | None |
| GPU required | None |

## Registry listings

SIGMA Guard MCP Server is listed on:

- [mcp.so](https://mcp.so) (search "sigma-guard")
- [smithery.ai](https://smithery.ai) (search "sigma-guard")
- [glama.ai/mcp](https://glama.ai/mcp) (search "sigma-guard")
- [GitHub MCP Registry](https://github.com/modelcontextprotocol/servers)

## Troubleshooting

**"MCP package not installed"**: Run `pip install sigma-guard[mcp]`
or `pip install 'mcp>=1.6'`.

**SSE deprecation warning**: Switch to `--transport streamable-http`.
SSE is deprecated as of MCP spec 2025-03-26.

**Connection refused on Streamable HTTP**: Check that the port is
not in use and the host binding is correct. The endpoint is at `/mcp`
(e.g. `http://localhost:8401/mcp`).
