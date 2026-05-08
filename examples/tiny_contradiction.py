# examples/tiny_contradiction.py
# The simplest possible contradiction demo.
#
# Two nodes. One edge. One disagreement.
# No setup required beyond: pip install numpy scipy
#
# Run:
#   cd sigma-guard
#   pip install -e .
#   python examples/tiny_contradiction.py

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sigma_guard import SigmaGuard


def main():
    guard = SigmaGuard()

    # Two nodes disagree on who the approved vendor is.
    # Policy says Supplier_A. Procurement says Supplier_B.
    guard.load_dict({
        "vertices": [
            {"id": "Policy", "label": "Policy", "claims": {"approved_vendor": "Supplier_A"}},
            {"id": "Procurement", "label": "Procurement", "claims": {"approved_vendor": "Supplier_B"}},
        ],
        "edges": [
            {"source": "Policy", "target": "Procurement", "relation": "governs"},
        ],
    })

    verdict = guard.verify()

    print("Tiny Contradiction Demo")
    print("=" * 40)
    print()
    print("Graph: 2 vertices, 1 edge")
    print("Policy says approved_vendor = Supplier_A")
    print("Procurement says approved_vendor = Supplier_B")
    print()

    if verdict.has_contradictions:
        print("Verdict: INCONSISTENT")
        for c in verdict.contradictions:
            print()
            print("  [%s] %s <-> %s" % (c.severity, c.location[0], c.location[1]))
            print("  %s" % c.explanation)
            print("  Proof: %s" % c.proof_id)
    else:
        print("Verdict: CONSISTENT")

    print()
    print("Elapsed: %.2fms" % verdict.elapsed_ms)


if __name__ == "__main__":
    main()
