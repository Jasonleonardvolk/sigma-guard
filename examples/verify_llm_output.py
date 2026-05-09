# examples/verify_llm_output.py
# Verify LLM-generated claims for structural contradictions.
#
# This example shows how SIGMA Guard can sit behind any LLM
# as a verification layer. The model generates claims. SIGMA
# checks whether those claims are structurally consistent.
#
# Run:
#   cd sigma-guard
#   pip install -e .
#   python examples/verify_llm_output.py

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sigma_guard import SigmaGuard


def main():
    guard = SigmaGuard()

    # Simulate LLM output containing claims about a component.
    # The LLM said two things that cannot both be true:
    #   1. Component_X ships in Q2 (ready to ship)
    #   2. Component_X production starts in Q3 (not yet produced)
    #
    # Both claims are plausible individually.
    # Together, they are structurally incompatible.

    print("LLM Verification Demo")
    print("=" * 50)
    print()
    print("LLM output:")
    print('  "Component X is scheduled to ship in Q2."')
    print('  "Component X production begins in Q3."')
    print()
    print("Extracting claims and building verification graph...")
    print()

    guard.load_dict({
        "vertices": [
            {
                "id": "shipping_claim",
                "label": "Component_X (shipping)",
                "claims": {
                    "timeline": "Q2",
                    "component_status": "ready_to_ship",
                },
            },
            {
                "id": "production_claim",
                "label": "Component_X (production)",
                "claims": {
                    "timeline": "Q3",
                    "component_status": "not_yet_produced",
                },
            },
        ],
        "edges": [
            {
                "source": "shipping_claim",
                "target": "production_claim",
                "relation": "same_component_timeline",
            },
        ],
    })

    verdict = guard.verify()

    if verdict.has_contradictions:
        print("Verdict: UNSAFE")
        print("LLM output contains structural contradictions.")
        print()
        for c in verdict.contradictions:
            print("  [%s] %s <-> %s" % (c.severity, c.location[0], c.location[1]))
            print("  %s" % c.explanation)
            print("  Proof: %s" % c.proof_id)
            print()
        print("Action: block, revise, or flag for human review.")
    else:
        print("Verdict: SAFE")
        print("Claims are structurally consistent.")

    print()
    print("Receipt: %s" % verdict.proof_id)
    print("Elapsed: %.2fms" % verdict.elapsed_ms)
    print()
    print("This receipt is independently verifiable.")
    print("The model does not matter. The verification does.")


if __name__ == "__main__":
    main()
