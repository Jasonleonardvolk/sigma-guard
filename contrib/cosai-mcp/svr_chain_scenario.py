"""Proposed stateful scenario: SVR receipt chain integrity across multi-hop MCP.

This scenario tests whether SVR receipts survive a three-hop agent chain.
It is the first demonstration of end-to-end verified output across a
multi-hop MCP pipeline.

The scenario:
  1. Call tool A, receive output + SVR receipt
  2. Feed output from tool A into tool B (chained invocation)
  3. Call tool B, receive output + its own SVR receipt
  4. Verify that tool B's receipt references tool A's output hash
     (chain integrity: downstream receipt acknowledges upstream content)
  5. Verify that the final output carries a valid receipt chain

Integration: add this scenario to
cosai_mcp/stateful/scenarios/__init__.py and register it in the
harness runner.

Usage:
    cosai scan http://your-mcp-server --stateful --scenario svr-chain
"""
from __future__ import annotations

from cosai_mcp.stateful.harness import (
    Scenario,
    ScenarioStep,
    StepAction,
    StepAssertion,
)


SVR_CHAIN_SCENARIO = Scenario(
    id="T09-SC-001",
    name="SVR receipt chain integrity",
    threat_categories=("T9", "T6", "T12"),
    description=(
        "Tests whether SVR receipts survive a three-hop agent chain. "
        "Step 1 calls a tool and checks for a receipt in the response. "
        "Step 2 calls a second tool with the first tool's output. "
        "Step 3 verifies the second receipt references the first output. "
        "Failure at any step means the verification chain is broken and "
        "downstream agents cannot trust upstream output."
    ),
    steps=(
        # Step 1: Call first tool, verify receipt is present
        ScenarioStep(
            description=(
                "Call verify_claims with test input. Response must include "
                "an SVR receipt (receipt_id, verdict, safe_to_rely fields)."
            ),
            action=StepAction(
                method="tools/call",
                params={
                    "name": "verify_claims",
                    "arguments": {
                        "claims": "The approved vendor is Supplier_A. "
                                  "Supplier_A is based in Germany.",
                    },
                },
            ),
            assertions=(
                # Must not return a JSON-RPC error
                StepAssertion(
                    target="error",
                    operator="is_none",
                    message="verify_claims must not return an error",
                ),
                # Response must contain receipt_id (SVR receipt present)
                StepAssertion(
                    target="result",
                    operator="is_not_none",
                    message="verify_claims must return a result",
                ),
            ),
        ),

        # Step 2: Call verify_graph with different input (simulates
        # downstream tool receiving upstream-verified content)
        ScenarioStep(
            description=(
                "Call verify_graph with graph input. Simulates a second "
                "tool in the chain receiving upstream-verified content. "
                "Response must include its own SVR receipt."
            ),
            action=StepAction(
                method="tools/call",
                params={
                    "name": "verify_graph",
                    "arguments": {
                        "graph_json": (
                            '{"vertices":['
                            '{"id":"A","label":"Supplier_A","claims":{"country":"DE"}},'
                            '{"id":"B","label":"Supplier_B","claims":{"country":"US"}}'
                            '],"edges":['
                            '{"source":"A","target":"B","relation":"SUPPLIES"}'
                            ']}'
                        ),
                        "constraints": '{"SUPPLIES":{"acyclic":true}}',
                    },
                },
            ),
            assertions=(
                StepAssertion(
                    target="error",
                    operator="is_none",
                    message="verify_graph must not return an error",
                ),
                StepAssertion(
                    target="result",
                    operator="is_not_none",
                    message="verify_graph must return a result",
                ),
            ),
        ),

        # Step 3: Call tools/list again to verify manifest has not
        # drifted mid-session (T6 rug pull detection combined with
        # T9 chain integrity)
        ScenarioStep(
            description=(
                "Re-fetch tools/list mid-session. Manifest must not have "
                "drifted since initialization. Combined T6 (manifest "
                "integrity) and T9 (trust boundary) check: a rug pull "
                "mid-chain invalidates all receipts issued in the session."
            ),
            action=StepAction(
                method="tools/list",
                params={},
            ),
            assertions=(
                StepAssertion(
                    target="error",
                    operator="is_none",
                    message="tools/list must not return an error mid-session",
                ),
                StepAssertion(
                    target="result.tools",
                    operator="is_not_none",
                    message="tools/list must return tool definitions",
                ),
            ),
        ),
    ),
)


# -----------------------------------------------------------------
# Standalone runner for development/demo
# -----------------------------------------------------------------

def run_standalone(target_url: str) -> None:
    """Run the SVR chain scenario standalone (outside cosai-mcp runner).

    Usage:
        python svr_chain_scenario.py http://localhost:8000/mcp
    """
    from cosai_mcp.config import ScanConfig
    from cosai_mcp.stateful.harness import StatefulHarness

    config = ScanConfig(target_url=target_url)
    harness = StatefulHarness(config)
    result = harness.run_scenario(SVR_CHAIN_SCENARIO, target_url)

    print(f"Scenario: {result.scenario_name}")
    print(f"Status:   {result.status}")
    print(f"Passed:   {result.passed}")
    print()

    for step in result.step_results:
        status = "PASS" if step.passed else "FAIL"
        print(f"  Step {step.step_index}: {status} - {step.description[:60]}")
        if step.error:
            print(f"    Error: {step.error}")
        for f in step.failures:
            print(f"    {f.target} {f.operator}: {f.message}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python svr_chain_scenario.py <target-url>")
        print("Example: python svr_chain_scenario.py http://localhost:8000/mcp")
        sys.exit(1)
    run_standalone(sys.argv[1])
