# sigma_guard/mcp_server.py
# MCP (Model Context Protocol) server for SIGMA Guard.
#
# Exposes SIGMA verification as MCP tools that any MCP-compatible
# agent (Hermes, Claude, etc.) can call before final answer emission.
#
# Usage:
#   sigma-guard-mcp                          # stdio transport (default)
#   sigma-guard-mcp --transport sse --port 8401   # SSE transport
#
# Tools exposed:
#   verify_graph    - verify a full graph for structural contradictions
#   verify_claims   - verify a list of LLM claims for consistency
#   check_write     - check if a proposed graph write creates contradictions
#
# May 2026 | Invariant Research | Patent Pending (U.S. App# 19/649,080)

import json
import sys
import argparse


def create_server():
    """Create and configure the SIGMA Guard MCP server."""
    try:
        from mcp.server import Server
        from mcp.types import Tool, TextContent
    except ImportError:
        print(
            "MCP package not installed. Install with:\n"
            "  pip install sigma-guard[mcp]\n"
            "  # or\n"
            "  pip install mcp",
            file=sys.stderr,
        )
        sys.exit(1)

    from sigma_guard import SigmaGuard

    server = Server("sigma-guard")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="verify_graph",
                description=(
                    "Verify a graph for structural contradictions using "
                    "sheaf cohomology. Accepts a JSON graph with vertices "
                    "(each having claims as key-value pairs) and edges. "
                    "Returns a deterministic verdict: CONSISTENT or "
                    "INCONSISTENT, with exact contradiction locations, "
                    "severity levels, and cryptographic proof IDs. "
                    "Use this before trusting graph data or LLM output "
                    "that contains structured claims."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "graph": {
                            "type": "object",
                            "description": (
                                "Graph data with 'vertices' and 'edges'. "
                                "Each vertex has 'id' and 'claims' (key-value). "
                                "Each edge has 'source', 'target', 'relation'."
                            ),
                            "properties": {
                                "vertices": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "label": {"type": "string"},
                                            "claims": {
                                                "type": "object",
                                                "additionalProperties": True,
                                            },
                                        },
                                        "required": ["id"],
                                    },
                                },
                                "edges": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "source": {"type": "string"},
                                            "target": {"type": "string"},
                                            "relation": {"type": "string"},
                                        },
                                        "required": ["source", "target"],
                                    },
                                },
                            },
                            "required": ["vertices", "edges"],
                        },
                    },
                    "required": ["graph"],
                },
            ),
            Tool(
                name="verify_claims",
                description=(
                    "Verify a list of claims extracted from LLM output "
                    "for structural consistency. Each claim is a statement "
                    "with a subject, property, and value. SIGMA builds a "
                    "verification graph and checks whether all claims can "
                    "be true simultaneously. Returns SAFE or UNSAFE with "
                    "a signed receipt. Use this to verify LLM output before "
                    "emitting it to the user."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "claims": {
                            "type": "array",
                            "description": (
                                "List of claims. Each claim has a 'subject' "
                                "(entity), 'property' (what is claimed), and "
                                "'value' (the claimed value)."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "subject": {
                                        "type": "string",
                                        "description": "Entity the claim is about",
                                    },
                                    "property": {
                                        "type": "string",
                                        "description": "What is being claimed",
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": "The claimed value",
                                    },
                                },
                                "required": ["subject", "property", "value"],
                            },
                        },
                    },
                    "required": ["claims"],
                },
            ),
            Tool(
                name="check_write",
                description=(
                    "Check whether a proposed graph write would create a "
                    "structural contradiction. Provide the current graph "
                    "and the proposed new edge. Returns whether the write "
                    "is safe or would create a contradiction, with proof."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "graph": {
                            "type": "object",
                            "description": "Current graph state (same format as verify_graph)",
                            "properties": {
                                "vertices": {"type": "array"},
                                "edges": {"type": "array"},
                            },
                            "required": ["vertices", "edges"],
                        },
                        "source": {
                            "type": "string",
                            "description": "Source vertex ID for the proposed write",
                        },
                        "target": {
                            "type": "string",
                            "description": "Target vertex ID for the proposed write",
                        },
                        "relation": {
                            "type": "string",
                            "description": "Relationship type for the proposed write",
                        },
                    },
                    "required": ["graph", "source", "target", "relation"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name == "verify_graph":
            return await _handle_verify_graph(arguments)
        elif name == "verify_claims":
            return await _handle_verify_claims(arguments)
        elif name == "check_write":
            return await _handle_check_write(arguments)
        else:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": "Unknown tool: %s" % name,
                    "available": ["verify_graph", "verify_claims", "check_write"],
                }),
            )]

    async def _handle_verify_graph(arguments: dict):
        graph_data = arguments.get("graph", {})
        if not graph_data.get("vertices"):
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": "Graph must contain at least one vertex.",
                    "expected_format": {
                        "vertices": [
                            {"id": "A", "claims": {"key": "value"}},
                        ],
                        "edges": [
                            {"source": "A", "target": "B", "relation": "rel"},
                        ],
                    },
                }),
            )]

        try:
            guard = SigmaGuard()
            guard.load_dict(graph_data)
            verdict = guard.verify()

            result = {
                "verdict": "INCONSISTENT" if verdict.has_contradictions else "CONSISTENT",
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

            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e)}),
            )]

    async def _handle_verify_claims(arguments: dict):
        claims = arguments.get("claims", [])
        if not claims:
            return [TextContent(
                type="text",
                text=json.dumps({"error": "No claims provided."}),
            )]

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

        # Create edges between all subjects that share at least one property
        edges = []
        subj_list = list(subjects.keys())
        for i in range(len(subj_list)):
            for j in range(i + 1, len(subj_list)):
                a = subj_list[i]
                b = subj_list[j]
                shared = set(subjects[a]["claims"].keys()) & set(subjects[b]["claims"].keys())
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
                    "Claims are structurally consistent under the "
                    "configured verification model."
                )

            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e)}),
            )]

    async def _handle_check_write(arguments: dict):
        graph_data = arguments.get("graph", {})
        source = arguments.get("source", "")
        target = arguments.get("target", "")
        relation = arguments.get("relation", "related_to")

        if not graph_data.get("vertices"):
            return [TextContent(
                type="text",
                text=json.dumps({"error": "Graph must contain at least one vertex."}),
            )]

        if not source or not target:
            return [TextContent(
                type="text",
                text=json.dumps({"error": "Both 'source' and 'target' are required."}),
            )]

        try:
            guard = SigmaGuard()
            guard.load_dict(graph_data)
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

            return [TextContent(type="text", text=json.dumps(output, indent=2))]

        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e)}),
            )]

    return server


def main():
    parser = argparse.ArgumentParser(
        description="SIGMA Guard MCP Server",
        epilog=(
            "Exposes SIGMA verification as MCP tools.\n"
            "Any MCP-compatible agent can call verify_graph, "
            "verify_claims, or check_write.\n\n"
            "Examples:\n"
            "  sigma-guard-mcp                    # stdio (default)\n"
            "  sigma-guard-mcp --transport sse    # SSE on port 8401\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8401,
        help="Port for SSE transport (default: 8401)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for SSE transport (default: 0.0.0.0)",
    )

    args = parser.parse_args()
    server = create_server()

    if args.transport == "stdio":
        from mcp.server.stdio import stdio_server
        import asyncio

        async def run_stdio():
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream)

        asyncio.run(run_stdio())

    elif args.transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route, Mount
        import uvicorn

        sse = SseServerTransport("/messages/")

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

        print(
            "SIGMA Guard MCP Server (SSE) on http://%s:%d"
            % (args.host, args.port)
        )
        print("Tools: verify_graph, verify_claims, check_write")
        uvicorn.run(starlette_app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
