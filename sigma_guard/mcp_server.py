# sigma_guard/mcp_server.py
# MCP (Model Context Protocol) server for SIGMA Guard.
#
# Exposes SIGMA verification as MCP tools that any MCP-compatible
# agent (Claude, Cursor, LangChain, LlamaIndex, etc.) can call
# to detect structural contradictions before trusting output.
#
# Usage:
#   sigma-guard-mcp                                      # stdio (default)
#   sigma-guard-mcp --transport streamable-http           # Streamable HTTP
#   sigma-guard-mcp --transport streamable-http --port 8401
#
# Tools exposed:
#   verify_graph    - verify a graph for structural contradictions
#   verify_claims   - verify LLM claims for consistency
#   check_write     - check if a proposed graph write is safe
#
# MCP Protocol: 2025-03-26+ (Streamable HTTP supported)
# May 2026 | Invariant Research

import json
import sys
import argparse


def create_server():
    """Create and configure the SIGMA Guard MCP server using FastMCP."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "MCP package not installed or outdated. Install with:\n"
            "  pip install sigma-guard[mcp]\n"
            "  # or\n"
            "  pip install 'mcp>=1.6'",
            file=sys.stderr,
        )
        sys.exit(1)

    from sigma_guard import SigmaGuard

    mcp = FastMCP(
        "sigma-guard",
        instructions=(
            "SIGMA Guard is a deterministic structural verification layer "
            "for knowledge graphs, agent state, and LLM output. It uses "
            "sheaf cohomology to detect contradictions that schema validation "
            "and constraint engines miss. Call verify_claims to check LLM "
            "output before emitting it. Call verify_graph to audit a full "
            "knowledge graph. Call check_write to gate a proposed mutation. "
            "Every verdict is deterministic, reproducible, and returns a "
            "cryptographically signed proof receipt. Zero ML. Zero GPU. "
            "35 microseconds per edit at 5 million vertices."
        ),
    )

    # ------------------------------------------------------------------
    # Tool: verify_graph
    # ------------------------------------------------------------------
    @mcp.tool(
        name="verify_graph",
        description=(
            "Detect structural contradictions in a knowledge graph, "
            "agent memory graph, compliance graph, or any graph where "
            "nodes carry claims that must be globally consistent. "
            "Uses cellular sheaf cohomology (H^1) to find contradictions "
            "that schema validation and constraint engines miss. "
            "Returns a deterministic verdict (CONSISTENT or INCONSISTENT), "
            "exact contradiction locations with severity rankings, "
            "Dirichlet energy per edge, and a cryptographic proof ID. "
            "Use BEFORE trusting retrieved graph data, after GraphRAG "
            "retrieval, after knowledge graph ETL merges, or when "
            "auditing agent memory for accumulated contradictions. "
            "Latency: sub-millisecond for typical graphs. "
            "No ML, no GPU, no training data, no probabilistic scoring. "
            "Every run on the same input produces the same output."
        ),
    )
    def verify_graph(
        graph: dict,
    ) -> str:
        """Verify a graph for structural contradictions.

        Args:
            graph: Graph data with 'vertices' and 'edges'.
                   Each vertex has 'id' and optional 'claims' (key-value pairs).
                   Each edge has 'source', 'target', and optional 'relation'.
                   Example:
                   {
                       "vertices": [
                           {"id": "Policy", "claims": {"vendor": "A"}},
                           {"id": "Procurement", "claims": {"vendor": "B"}}
                       ],
                       "edges": [
                           {"source": "Policy", "target": "Procurement",
                            "relation": "governs"}
                       ]
                   }

        Returns:
            JSON with verdict, contradiction details, and proof receipt.
        """
        if not graph.get("vertices"):
            return json.dumps({
                "error": "Graph must contain at least one vertex.",
                "expected_format": {
                    "vertices": [
                        {"id": "A", "claims": {"key": "value"}},
                    ],
                    "edges": [
                        {"source": "A", "target": "B", "relation": "rel"},
                    ],
                },
            })

        try:
            guard = SigmaGuard()
            guard.load_dict(graph)
            verdict = guard.verify()

            result = {
                "verdict": (
                    "INCONSISTENT" if verdict.has_contradictions
                    else "CONSISTENT"
                ),
                "safe_to_rely_on": not verdict.has_contradictions,
                "contradiction_count": verdict.contradiction_count,
                "h1_dimension": verdict.h1_dimension,
                "spectral_gap": round(verdict.spectral_gap, 4),
                "total_energy": round(verdict.total_energy, 6),
                "elapsed_ms": round(verdict.elapsed_ms, 3),
                "receipt_id": verdict.proof_id,
                "algorithm": "sheaf_cohomology_h1",
                "deterministic": True,
            }

            if verdict.has_contradictions:
                result["contradictions"] = []
                for c in verdict.contradictions:
                    result["contradictions"].append({
                        "severity": c.severity,
                        "location": list(c.location),
                        "energy": round(c.energy, 4),
                        "explanation": c.explanation,
                        "proof_id": c.proof_id,
                    })

            return json.dumps(result, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------
    # Tool: verify_claims
    # ------------------------------------------------------------------
    @mcp.tool(
        name="verify_claims",
        description=(
            "Verify a list of claims extracted from LLM output, RAG "
            "retrieval, or agent reasoning for structural consistency. "
            "Detects hallucinations where an LLM asserts contradictory "
            "facts in the same response or across conversation turns. "
            "Each claim has a subject (entity), property (attribute), "
            "and value (what is asserted). SIGMA builds a verification "
            "graph from the claims and checks whether all claims can be "
            "true simultaneously using sheaf cohomology. "
            "Returns SAFE or UNSAFE with a signed proof receipt. "
            "Use BEFORE emitting LLM output to the user, after RAG "
            "retrieval to check retrieved facts agree, or when an agent "
            "accumulates state across multiple tool calls. "
            "If UNSAFE: revise the output, flag for human review, or "
            "block emission entirely. "
            "Zero ML. Deterministic. Same input always yields same verdict."
        ),
    )
    def verify_claims(
        claims: list,
    ) -> str:
        """Verify claims for structural consistency.

        Args:
            claims: List of claim objects. Each has:
                    - subject (str): entity the claim is about
                    - property (str): what is being claimed
                    - value (str): the claimed value
                    Example:
                    [
                        {"subject": "ComponentX", "property": "ships", "value": "Q2"},
                        {"subject": "ComponentX", "property": "production_start",
                         "value": "Q3"}
                    ]

        Returns:
            JSON with verdict (SAFE/UNSAFE), contradiction details,
            and proof receipt.
        """
        if not claims:
            return json.dumps({"error": "No claims provided."})

        # Group claims by subject to build vertices
        subjects = {}
        for claim in claims:
            subj = claim.get("subject", "unknown")
            prop = claim.get("property", "unknown")
            val = claim.get("value", "")
            if subj not in subjects:
                subjects[subj] = {"id": subj, "label": subj, "claims": {}}
            subjects[subj]["claims"][prop] = val

        vertices = list(subjects.values())

        # Create edges between subjects that share at least one property
        edges = []
        subj_list = list(subjects.keys())
        for i in range(len(subj_list)):
            for j in range(i + 1, len(subj_list)):
                a = subj_list[i]
                b = subj_list[j]
                shared = (
                    set(subjects[a]["claims"].keys())
                    & set(subjects[b]["claims"].keys())
                )
                if shared:
                    edges.append({
                        "source": a,
                        "target": b,
                        "relation": "shared_claims",
                    })

        # If no edges from shared properties, connect all subjects
        # (they may be making claims about the same domain)
        if not edges and len(subj_list) > 1:
            for i in range(len(subj_list)):
                for j in range(i + 1, len(subj_list)):
                    edges.append({
                        "source": subj_list[i],
                        "target": subj_list[j],
                        "relation": "same_domain",
                    })

        graph_data = {"vertices": vertices, "edges": edges}

        try:
            guard = SigmaGuard()
            guard.load_dict(graph_data)
            verdict = guard.verify()

            result = {
                "verdict": "UNSAFE" if verdict.has_contradictions else "SAFE",
                "safe_to_rely_on": not verdict.has_contradictions,
                "claims_checked": len(claims),
                "subjects_found": len(subjects),
                "edges_tested": len(edges),
                "contradiction_count": verdict.contradiction_count,
                "elapsed_ms": round(verdict.elapsed_ms, 3),
                "receipt_id": verdict.proof_id,
                "deterministic": True,
            }

            if verdict.has_contradictions:
                result["contradictions"] = []
                for c in verdict.contradictions:
                    result["contradictions"].append({
                        "severity": c.severity,
                        "location": list(c.location),
                        "explanation": c.explanation,
                        "proof_id": c.proof_id,
                    })
                result["recommendation"] = (
                    "LLM output contains structural contradictions. "
                    "Revise, flag for human review, or block emission."
                )
            else:
                result["recommendation"] = (
                    "Claims are structurally consistent. "
                    "Safe to emit or commit."
                )

            return json.dumps(result, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------
    # Tool: check_write
    # ------------------------------------------------------------------
    @mcp.tool(
        name="check_write",
        description=(
            "Check whether a proposed graph mutation would create a "
            "structural contradiction BEFORE committing the write. "
            "Acts as a pre-commit verification gate for knowledge "
            "graphs, agent memory stores, and any system that mutates "
            "graph state. Provide the current graph and the proposed "
            "new edge. Returns whether the write is safe to commit or "
            "would introduce a contradiction, with a deterministic "
            "proof and sub-millisecond latency (35 microseconds at "
            "5M vertices). "
            "Use as a write guard in GraphRAG pipelines, agent memory "
            "systems, Memgraph/Neo4j pre-commit hooks, or any workflow "
            "where graph mutations must preserve consistency. "
            "If the write creates a contradiction: block the commit "
            "and return the proof to the caller."
        ),
    )
    def check_write(
        graph: dict,
        source: str,
        target: str,
        relation: str = "related_to",
    ) -> str:
        """Check if a proposed write would create a contradiction.

        Args:
            graph: Current graph state with 'vertices' and 'edges'
                   (same format as verify_graph).
            source: Source vertex ID for the proposed edge.
            target: Target vertex ID for the proposed edge.
            relation: Relationship type for the proposed edge.

        Returns:
            JSON with safe_to_commit flag and proof if contradiction found.
        """
        if not graph.get("vertices"):
            return json.dumps({
                "error": "Graph must contain at least one vertex.",
            })

        if not source or not target:
            return json.dumps({
                "error": "Both 'source' and 'target' are required.",
            })

        try:
            guard = SigmaGuard()
            guard.load_dict(graph)
            result = guard.check_write(source, target, relation)

            output = {
                "write": "%s -> %s (%s)" % (source, target, relation),
                "creates_contradiction": result.creates_contradiction,
                "safe_to_commit": not result.creates_contradiction,
                "elapsed_us": round(result.elapsed_us, 1),
                "deterministic": True,
            }

            if result.creates_contradiction:
                output["severity"] = result.severity
                output["conflicting_nodes"] = result.conflicting_nodes
                output["explanation"] = result.explanation
                output["proof_id"] = result.proof_id
                output["recommendation"] = "Block this write."
            else:
                output["recommendation"] = "Write is safe to commit."

            return json.dumps(output, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

    return mcp


def main():
    parser = argparse.ArgumentParser(
        description="SIGMA Guard MCP Server",
        epilog=(
            "Exposes SIGMA verification as MCP tools.\n"
            "Any MCP-compatible agent can call verify_graph, "
            "verify_claims, or check_write.\n\n"
            "Examples:\n"
            "  sigma-guard-mcp                              # stdio\n"
            "  sigma-guard-mcp --transport streamable-http   # HTTP\n"
            "  sigma-guard-mcp --transport streamable-http --port 8401\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help=(
            "Transport mode. 'stdio' for local agents (Claude Desktop, "
            "Cursor). 'streamable-http' for remote agents and production "
            "deployment (recommended for remote). 'sse' is deprecated "
            "but kept for backward compatibility. Default: stdio."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8401,
        help="Port for HTTP transport (default: 8401)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP transport (default: 0.0.0.0)",
    )

    args = parser.parse_args()
    mcp = create_server()

    if args.transport == "stdio":
        mcp.run(transport="stdio")

    elif args.transport == "streamable-http":
        # FastMCP.run() does not accept host/port as kwargs.
        # Set them on settings before calling run().
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        print(
            "SIGMA Guard MCP Server (Streamable HTTP) on "
            "http://%s:%d%s" % (
                args.host, args.port,
                mcp.settings.streamable_http_path,
            )
        )
        print("Tools: verify_graph, verify_claims, check_write")
        mcp.run(transport="streamable-http")

    elif args.transport == "sse":
        # Backward compatibility: SSE is deprecated as of MCP 2025-03-26
        # but some older clients may still need it.
        print(
            "WARNING: SSE transport is deprecated. "
            "Use --transport streamable-http for remote deployment."
        )
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        print(
            "SIGMA Guard MCP Server (SSE) on "
            "http://%s:%d" % (args.host, args.port)
        )
        print("Tools: verify_graph, verify_claims, check_write")
        try:
            mcp.run(transport="sse")
        except Exception:
            # If FastMCP doesn't support sse flag, fall back to
            # legacy SseServerTransport
            print("FastMCP SSE not available, using legacy transport...")
            _run_legacy_sse(args.host, args.port)


def _run_legacy_sse(host, port):
    """Fallback for older mcp versions that need manual SSE setup."""
    try:
        from mcp.server import Server
        from mcp.server.sse import SseServerTransport
        from mcp.types import Tool, TextContent
        from starlette.applications import Starlette
        from starlette.routing import Route, Mount
        import uvicorn
    except ImportError as e:
        print("Legacy SSE requires: pip install mcp starlette uvicorn")
        print("Error: %s" % e)
        sys.exit(1)

    # Re-create using low-level API for SSE compatibility
    from sigma_guard import SigmaGuard
    import asyncio

    server = Server("sigma-guard")
    sse = SseServerTransport("/messages/")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="verify_graph",
                description="Verify a graph for structural contradictions.",
                inputSchema={"type": "object", "properties": {
                    "graph": {"type": "object"}
                }, "required": ["graph"]},
            ),
            Tool(
                name="verify_claims",
                description="Verify LLM claims for consistency.",
                inputSchema={"type": "object", "properties": {
                    "claims": {"type": "array"}
                }, "required": ["claims"]},
            ),
            Tool(
                name="check_write",
                description="Check if a proposed graph write is safe.",
                inputSchema={"type": "object", "properties": {
                    "graph": {"type": "object"},
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "relation": {"type": "string"},
                }, "required": ["graph", "source", "target"]},
            ),
        ]

    @server.call_tool()
    async def call_tool(name, arguments):
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": (
                    "SSE transport is deprecated. Please upgrade to "
                    "streamable-http. Run: sigma-guard-mcp "
                    "--transport streamable-http"
                ),
            }),
        )]

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(streams[0], streams[1])

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

    uvicorn.run(starlette_app, host=host, port=port)


if __name__ == "__main__":
    main()
