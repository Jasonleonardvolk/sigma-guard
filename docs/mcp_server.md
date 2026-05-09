# MCP Server Integration

SIGMA Guard runs as an MCP (Model Context Protocol) server, exposing
deterministic graph verification as tools that any MCP-compatible
agent can call.

## Install

```
pip install sigma-guard[mcp]
```

## Run

```
# stdio transport (default, for Claude Desktop, Hermes, etc.)
sigma-guard-mcp

# SSE transport (for web-based agents)
sigma-guard-mcp --transport sse --port 8401
```

## Tools

The server exposes three tools:

### verify_graph

Verify a full graph for structural contradictions.

Input: a JSON graph with vertices (each having claims) and edges.
Output: CONSISTENT or INCONSISTENT, with contradiction locations,
severity, energy, and cryptographic proof IDs.

### verify_claims

Verify a list of claims extracted from LLM output. Each claim has
a subject, property, and value. SIGMA builds a verification graph
from the claims and checks structural consistency.

Input: list of claims.
Output: SAFE or UNSAFE, with a signed receipt.

### check_write

Check whether a proposed graph write would create a contradiction.

Input: current graph state plus proposed source, target, and relation.
Output: safe to commit or contradiction detected, with proof.

## Agent configuration

### Hermes Agent

Add to your Hermes MCP configuration:

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

Hermes can then call `verify_claims` before emitting an answer:

```
User asks a question
-> Hermes generates answer
-> Hermes extracts claims
-> Hermes calls verify_claims tool
-> SIGMA returns SAFE or UNSAFE with receipt
-> Hermes emits (if SAFE) or revises (if UNSAFE)
```

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

### Any MCP-compatible agent

The server uses standard MCP protocol. Any agent that supports
MCP tool calls can connect via stdio or SSE.

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

## Architecture

```
Any LLM (OpenAI, Anthropic, Meta, Mistral, Nous, local)
        |
        v
Agent framework (Hermes, Claude, custom)
        |
        v
MCP tool call: verify_claims or verify_graph
        |
        v
SIGMA Guard MCP Server
        |
        v
Sheaf cohomology verification (deterministic)
        |
        v
Verdict + signed receipt returned to agent
        |
        v
Agent decides: emit, revise, block, or flag
```

The model does not matter. The verification does.
