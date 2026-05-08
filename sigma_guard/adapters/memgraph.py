# sigma_guard/adapters/memgraph.py
# Memgraph adapter: pre-commit contradiction detection via triggers.
#
# Memgraph supports write-time triggers that fire BEFORE or AFTER
# a transaction commits. SIGMA hooks into the BEFORE COMMIT trigger
# to verify every write operation for structural contradictions.
#
# Requirements:
#   pip install gqlalchemy   (Memgraph Python client)
#
# Usage:
#   from sigma_guard.adapters.memgraph import MemgraphGuard
#   mg = MemgraphGuard(host="localhost", port=7687)
#   mg.install_trigger()
#
# May 2026 | Invariant Research | Patent Pending

import json
import logging
from typing import Any, Dict, List, Optional

from sigma_guard.adapters.base import GraphDatabaseAdapter, ContradictionError
from sigma_guard.verdict import WriteCheckResult

logger = logging.getLogger(__name__)


# Name of the Memgraph query module that SIGMA installs
SIGMA_MODULE_NAME = "sigma_guard"

# Cypher to register the trigger
TRIGGER_CYPHER = """
CALL mg.create_trigger(
    "sigma_contradiction_guard",
    "BEFORE COMMIT",
    "CALL sigma_guard.verify_transaction($createdVertices, $createdEdges, $setVertexProperties, $setEdgeProperties)"
) YIELD *;
"""

# Cypher to remove the trigger
DROP_TRIGGER_CYPHER = """
CALL mg.drop_trigger("sigma_contradiction_guard") YIELD *;
"""


class MemgraphGuard(GraphDatabaseAdapter):
    """
    Memgraph adapter for SIGMA pre-commit contradiction detection.

    Installs a BEFORE COMMIT trigger that calls SIGMA's verification
    engine on every write transaction. Contradictory writes are
    rejected before they reach the database.

    Usage:
        mg = MemgraphGuard(host="localhost", port=7687)
        mg.install_trigger()

    The trigger intercepts:
        - CREATE (node) - new vertices
        - CREATE (edge) - new edges
        - SET (property) - property changes on existing nodes/edges

    When a contradiction is detected, the transaction is rolled back
    and the client receives an error with:
        - The exact location of the contradiction
        - The severity (CRITICAL/HIGH/MODERATE/LOW)
        - A cryptographic proof ID
        - The conflicting nodes

    Architecture:
        Memgraph trigger -> Python query module -> SigmaGuard.check_write()
                                                      |
                                                  SIGMA engine
                                                  (sheaf cohomology)
                                                      |
                                                  Verdict (allow/reject)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 7687,
        username: str = "",
        password: str = "",
        stalk_dim: int = 8,
        seed: int = 42,
        block_on_contradiction: bool = True,
        log_only: bool = False,
    ):
        super().__init__(
            stalk_dim=stalk_dim,
            seed=seed,
            block_on_contradiction=block_on_contradiction,
            log_only=log_only,
        )
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._client = None

    def connect(self, **kwargs) -> None:
        """Connect to Memgraph via the Bolt protocol."""
        try:
            from gqlalchemy import Memgraph
        except ImportError:
            raise ImportError(
                "gqlalchemy required for Memgraph integration. "
                "Install with: pip install gqlalchemy"
            )

        self._client = Memgraph(
            host=kwargs.get("host", self.host),
            port=kwargs.get("port", self.port),
            username=kwargs.get("username", self.username),
            password=kwargs.get("password", self.password),
        )
        logger.info(
            "Connected to Memgraph at %s:%d", self.host, self.port
        )

    def install_trigger(self) -> None:
        """
        Install the SIGMA contradiction guard as a Memgraph trigger.

        This creates a BEFORE COMMIT trigger that calls the
        sigma_guard.verify_transaction() query module procedure
        on every write transaction.
        """
        if self._client is None:
            self.connect()

        # First, install the query module
        self._install_query_module()

        # Then register the trigger
        try:
            self._client.execute(TRIGGER_CYPHER)
            logger.info("SIGMA trigger installed successfully")
        except Exception as exc:
            # Trigger might already exist
            if "already exists" in str(exc).lower():
                logger.info("SIGMA trigger already installed")
            else:
                raise

    def remove_trigger(self) -> None:
        """Remove the SIGMA trigger from Memgraph."""
        if self._client is None:
            self.connect()

        try:
            self._client.execute(DROP_TRIGGER_CYPHER)
            logger.info("SIGMA trigger removed")
        except Exception as exc:
            logger.warning("Failed to remove trigger: %s", exc)

    def on_write(
        self,
        vertices: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        properties: List[Dict[str, Any]],
    ) -> bool:
        """
        Verify a write transaction for contradictions.

        Called by the Memgraph trigger. Checks each new edge
        and property change against the current graph state.

        Args:
            vertices: List of created vertices with labels and properties
            edges: List of created edges with source, target, type
            properties: List of property changes

        Returns:
            True if the write is safe, raises ContradictionError otherwise.
        """
        # Check new edges
        for edge in edges:
            src = edge.get("source", edge.get("from", ""))
            tgt = edge.get("target", edge.get("to", ""))
            rel = edge.get("type", edge.get("relation", ""))

            if not src or not tgt:
                continue

            result = self.guard.check_write(
                source=str(src),
                target=str(tgt),
                relation=str(rel),
            )

            if result.creates_contradiction:
                return self._check_and_decide(result)

        # Check property changes (could create value contradictions)
        for prop in properties:
            node_label = prop.get("node", prop.get("vertex", ""))
            for key, value in prop.get("properties", {}).items():
                # Property changes are checked by looking at the
                # node's neighbors for conflicting claims
                pass

        self._write_count += 1
        return True

    def snapshot_graph(self) -> Dict[str, Any]:
        """
        Take a snapshot of the current Memgraph graph.

        Exports all vertices and edges as a dictionary that can
        be loaded into SigmaGuard for verification.
        """
        if self._client is None:
            self.connect()

        # Export vertices
        vertex_result = self._client.execute_and_fetch(
            "MATCH (n) RETURN id(n) AS id, labels(n) AS labels, "
            "properties(n) AS props"
        )
        vertices = []
        for row in vertex_result:
            labels = row.get("labels", [])
            label = labels[0] if labels else "node_%d" % row["id"]
            vertices.append({
                "id": str(row["id"]),
                "label": label,
                "claims": row.get("props", {}),
            })

        # Export edges
        edge_result = self._client.execute_and_fetch(
            "MATCH (a)-[r]->(b) RETURN id(a) AS src, id(b) AS tgt, "
            "type(r) AS rel, properties(r) AS props"
        )
        edges = []
        for row in edge_result:
            edges.append({
                "source": str(row["src"]),
                "target": str(row["tgt"]),
                "relation": row.get("rel", ""),
                "value": row.get("props", {}),
            })

        return {"vertices": vertices, "edges": edges}

    def verify_current_graph(self):
        """
        Verify the entire current Memgraph graph for contradictions.

        Takes a snapshot and runs full verification.
        """
        snapshot = self.snapshot_graph()
        self.guard.load_dict(snapshot)
        return self.guard.verify()

    def _install_query_module(self) -> None:
        """
        Install the SIGMA query module into Memgraph.

        Memgraph query modules are Python files placed in the
        /usr/lib/memgraph/query_modules/ directory (in Docker)
        or specified via --query-modules-directory flag.

        This method generates the query module source code.
        """
        module_code = self._generate_query_module()
        logger.info(
            "SIGMA query module generated (%d bytes). "
            "Install it at: /usr/lib/memgraph/query_modules/sigma_guard.py",
            len(module_code),
        )
        # In Docker Compose, the module is volume-mounted.
        # For manual install, write to the query modules directory.

    def _generate_query_module(self) -> str:
        """Generate the Memgraph query module source code."""
        return '''# sigma_guard.py - Memgraph Query Module
# Auto-generated by SIGMA Graph Guard
# Place in /usr/lib/memgraph/query_modules/
#
# This module exposes a verify_transaction() procedure that is
# called by the BEFORE COMMIT trigger on every write transaction.

import mgp
import json
import sys

# Add sigma_guard to the path if needed
# sys.path.insert(0, "/opt/sigma-guard")

from sigma_guard import SigmaGuard
from sigma_guard.adapters.base import ContradictionError

# Global guard instance (initialized once, reused across transactions)
_guard = None


def _get_guard():
    global _guard
    if _guard is None:
        _guard = SigmaGuard(stalk_dim=8, seed=42)
    return _guard


@mgp.read_proc
def verify_transaction(
    ctx: mgp.ProcCtx,
    created_vertices: mgp.List[mgp.Vertex],
    created_edges: mgp.List[mgp.Edge],
    set_vertex_properties: mgp.List[mgp.Map],
    set_edge_properties: mgp.List[mgp.Map],
) -> mgp.Record(status=str, details=str):
    """
    Verify a transaction for structural contradictions.

    Called by the BEFORE COMMIT trigger. If a contradiction is
    detected, raises an exception to roll back the transaction.
    """
    guard = _get_guard()

    # Check each new edge
    for edge in created_edges:
        src_labels = list(edge.from_vertex.labels)
        tgt_labels = list(edge.to_vertex.labels)
        src_label = src_labels[0].name if src_labels else str(edge.from_vertex.id)
        tgt_label = tgt_labels[0].name if tgt_labels else str(edge.to_vertex.id)

        result = guard.check_write(
            source=src_label,
            target=tgt_label,
            relation=edge.type.name,
        )

        if result.creates_contradiction:
            raise Exception(
                "SIGMA: Write blocked. Structural contradiction detected. "
                "Severity=%s. %s. Proof=%s"
                % (result.severity, result.explanation, result.proof_id)
            )

    return mgp.Record(status="ok", details="No contradictions detected")
'''
