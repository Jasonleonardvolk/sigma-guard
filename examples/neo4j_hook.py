# examples/neo4j_hook.py
# Full working example: SIGMA as a Neo4j write verifier.
#
# Prerequisites:
#   pip install neo4j
#   Neo4j running on bolt://localhost:7687
#
# This script:
#   1. Connects to Neo4j
#   2. Loads the current graph into SIGMA
#   3. Executes writes through the guard (verified before commit)

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sigma_guard.adapters.neo4j import Neo4jGuard
from sigma_guard.adapters.base import ContradictionError


def main():
    print("SIGMA Graph Guard: Neo4j Integration Demo")
    print("=" * 50)
    print()

    guard = Neo4jGuard(
        uri="bolt://localhost:7687",
        auth=("neo4j", "password"),
        block_on_contradiction=True,
    )

    try:
        guard.connect()
    except Exception as exc:
        print("Could not connect to Neo4j: %s" % exc)
        print("Start Neo4j and update the connection details.")
        return

    print("Connected to Neo4j")

    # Load current graph state
    guard.install_transaction_listener()
    print("Graph loaded into SIGMA")
    print()

    # Verify current state
    verdict = guard.verify_current_graph()
    print("Current graph:")
    print("  Vertices: %d" % verdict.graph_stats["vertices"])
    print("  Contradictions: %d" % verdict.contradiction_count)
    print()

    # Execute a verified write
    print("Creating a supplier node...")
    try:
        guard.execute(
            "CREATE (s:Supplier {name: 'Acme', sole_source: true})"
        )
        print("  Write accepted")
    except ContradictionError as exc:
        print("  BLOCKED: %s" % exc)
    print()

    # Clean up
    guard.close()
    print("Done.")


if __name__ == "__main__":
    main()
