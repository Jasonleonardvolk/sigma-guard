# examples/basic_usage.py
# Full pipeline demo: requires the SIGMA core engine.
#
# This example connects the open adapter layer to the SIGMA
# verification engine. If you see "SIGMA core engine not found",
# use the Docker image instead:
#
#   docker run jasonvolk/sigma-guard demo supply_chain
#
# To run locally with the engine on your PYTHONPATH:
#   $env:PYTHONPATH = "C:\Dev\kha"
#   python examples\basic_usage.py

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sigma_guard import SigmaGuard


def main():
    guard = SigmaGuard(stalk_dim=8, seed=42)

    # Load a dataset with known contradictions
    guard.load_json("datasets/supply_chain.json")

    # Full verification
    verdict = guard.verify()
    print(verdict.summary())
    print()

    # Check individual writes
    print("=" * 40)
    print("Incremental write checks:")
    print("=" * 40)
    print()

    # SAFE write: Factory_West -> Supplier_A
    # No shared claim keys, so no semantic disagreement.
    result = guard.check_write(
        source="Factory_West",
        target="Supplier_A",
        relation="sources_from",
    )
    print("1. Write Factory_West -> Supplier_A (sources_from):")
    print("   Creates contradiction: %s" % result.creates_contradiction)
    print("   Elapsed: %.1f us" % result.elapsed_us)
    print()

    # BLOCKED write: Procurement -> Quality_Board
    # Both have "approved_vendors_component_x" with different values
    # (Procurement says 1, Quality_Board says 2). This is a structural
    # disagreement that SIGMA should catch.
    result = guard.check_write(
        source="Procurement",
        target="Quality_Board",
        relation="policy_alignment",
    )
    print("2. Write Procurement -> Quality_Board (policy_alignment):")
    print("   Creates contradiction: %s" % result.creates_contradiction)
    if result.creates_contradiction:
        print("   Severity: %s" % result.severity)
        print("   Conflicting nodes: %s" % ", ".join(result.conflicting_nodes))
        print("   %s" % result.explanation)
        print("   Proof: %s" % result.proof_id)
    print("   Elapsed: %.1f us" % result.elapsed_us)


if __name__ == "__main__":
    main()
