# examples/langchain_mcp_example.py
#
# Demonstrates using SIGMA Guard MCP Server with LangChain
# via the langchain-mcp-adapters library.
#
# Prerequisites:
#   pip install sigma-guard[mcp] langchain-mcp-adapters langchain-anthropic
#
# Start the MCP server first:
#   sigma-guard-mcp --transport streamable-http --port 8401
#
# Then run this script:
#   python examples/langchain_mcp_example.py

import asyncio
import json


async def main():
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        print(
            "langchain-mcp-adapters not installed. Run:\n"
            "  pip install langchain-mcp-adapters"
        )
        return

    print("Connecting to SIGMA Guard MCP Server...")
    print()

    async with MultiServerMCPClient(
        {
            "sigma-guard": {
                "url": "http://localhost:8401/mcp",
                "transport": "streamable_http",
            }
        }
    ) as client:
        tools = client.get_tools()
        print("Available tools:")
        for tool in tools:
            print("  - %s" % tool.name)
        print()

        # Example 1: Verify consistent claims
        print("=" * 50)
        print("Example 1: Consistent claims")
        print("=" * 50)

        consistent_claims = json.dumps({
            "claims": [
                {
                    "subject": "Server_A",
                    "property": "status",
                    "value": "active",
                },
                {
                    "subject": "Server_B",
                    "property": "status",
                    "value": "active",
                },
            ]
        })

        for tool in tools:
            if tool.name == "verify_claims":
                result = await tool.ainvoke(consistent_claims)
                parsed = json.loads(result)
                print("Verdict: %s" % parsed.get("verdict"))
                print("Safe to rely on: %s" % parsed.get("safe_to_rely_on"))
                print()
                break

        # Example 2: Verify contradictory claims
        print("=" * 50)
        print("Example 2: Contradictory claims (hallucination)")
        print("=" * 50)

        contradictory_claims = json.dumps({
            "claims": [
                {
                    "subject": "Policy_Doc",
                    "property": "approved_vendor",
                    "value": "Supplier_A",
                },
                {
                    "subject": "Procurement_Record",
                    "property": "approved_vendor",
                    "value": "Supplier_B",
                },
            ]
        })

        for tool in tools:
            if tool.name == "verify_claims":
                result = await tool.ainvoke(contradictory_claims)
                parsed = json.loads(result)
                print("Verdict: %s" % parsed.get("verdict"))
                print("Safe to rely on: %s" % parsed.get("safe_to_rely_on"))
                print(
                    "Contradictions: %s"
                    % parsed.get("contradiction_count")
                )
                if parsed.get("contradictions"):
                    for c in parsed["contradictions"]:
                        print(
                            "  [%s] %s"
                            % (c["severity"], c["explanation"])
                        )
                print("Receipt: %s" % parsed.get("receipt_id"))
                print()
                break

        # Example 3: Verify a graph
        print("=" * 50)
        print("Example 3: Graph verification")
        print("=" * 50)

        graph_data = json.dumps({
            "graph": {
                "vertices": [
                    {
                        "id": "Asset_001",
                        "claims": {"state": "decommissioned"},
                    },
                    {
                        "id": "Traffic_Log",
                        "claims": {"state": "active_connections"},
                    },
                ],
                "edges": [
                    {
                        "source": "Asset_001",
                        "target": "Traffic_Log",
                        "relation": "network_state",
                    },
                ],
            }
        })

        for tool in tools:
            if tool.name == "verify_graph":
                result = await tool.ainvoke(graph_data)
                parsed = json.loads(result)
                print("Verdict: %s" % parsed.get("verdict"))
                print(
                    "Contradictions: %s"
                    % parsed.get("contradiction_count")
                )
                print(
                    "Elapsed: %s ms" % parsed.get("elapsed_ms")
                )
                print("Receipt: %s" % parsed.get("receipt_id"))
                print()
                break

    print("Done. All tools verified.")


if __name__ == "__main__":
    asyncio.run(main())
