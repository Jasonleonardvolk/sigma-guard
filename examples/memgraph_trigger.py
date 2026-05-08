# examples/memgraph_trigger.py
# Full working example: SIGMA as a Memgraph pre-commit trigger.
#
# Prerequisites:
#   1. Docker running
#   2. docker compose up (from the repo root)
#   3. pip install gqlalchemy
#
# This script:
#   1. Connects to Memgraph
#   2. Installs the SIGMA trigger
#   3. Creates some nodes and edges
#   4. Attempts a contradictory write (which gets blocked)

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sigma_guard.adapters.memgraph import MemgraphGuard
from sigma_guard.adapters.base import ContradictionError


def main():
    print("SIGMA Graph Guard: Memgraph Integration Demo")
    print("=" * 50)
    print()

    # Connect to Memgraph
    mg = MemgraphGuard(
        host="localhost",
        port=7687,
        stalk_dim=8,
        block_on_contradiction=True,
    )

    try:
        mg.connect()
    except Exception as exc:
        print("Could not connect to Memgraph: %s" % exc)
        print()
        print("Start Memgraph with: docker compose up -d")
        print("Or: docker run -p 7687:7687 memgraph/memgraph")
        return

    print("Connected to Memgraph")
    print()

    # Verify the current graph (before any writes)
    print("Verifying current graph state...")
    verdict = mg.verify_current_graph()
    print("  Vertices: %d" % verdict.graph_stats["vertices"])
    print("  Edges: %d" % verdict.graph_stats["edges"])
    print("  Contradictions: %d" % verdict.contradiction_count)
    print()

    # Install the trigger
    print("Installing SIGMA trigger...")
    mg.install_trigger()
    print("Trigger installed. All writes are now verified.")
    print()

    # Simulate some writes
    print("Simulating writes...")
    print()

    # Safe write: create a supplier
    print("1. Creating Supplier_A (sole source for Component_X)...")
    mg.on_write(
        vertices=[{"label": "Supplier_A", "properties": {"sole_source": True}}],
        edges=[{"source": "Supplier_A", "target": "Component_X", "type": "supplies"}],
        properties=[],
    )
    print("   OK: Write accepted")
    print()

    # Contradictory write: create a second sole source
    print("2. Creating Supplier_B (also sole source for Component_X)...")
    try:
        mg.on_write(
            vertices=[{"label": "Supplier_B", "properties": {"sole_source": True}}],
            edges=[{"source": "Supplier_B", "target": "Component_X", "type": "supplies"}],
            properties=[],
        )
        print("   OK: Write accepted (no contradiction detected)")
    except ContradictionError as exc:
        print("   BLOCKED: %s" % exc)
        print("   Severity: %s" % exc.result.severity)
        print("   Proof: %s" % exc.result.proof_id)
    print()

    # Print stats
    stats = mg.stats()
    print("Adapter stats:")
    print("  Writes checked: %d" % stats["writes_checked"])
    print("  Writes blocked: %d" % stats["writes_blocked"])
    print("  Block rate: %.1f%%" % (stats["block_rate"] * 100))


if __name__ == "__main__":
    main()
