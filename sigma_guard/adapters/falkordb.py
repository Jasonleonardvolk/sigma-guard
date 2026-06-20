# sigma_guard/adapters/falkordb.py
# FalkorDB adapter: contradiction detection for knowledge graphs.
#
# FalkorDB is a high-performance graph database using GraphBLAS
# sparse matrices. It supports OpenCypher queries and is
# purpose-built for Knowledge Graphs and GraphRAG.
#
# Requirements:
#   pip install falkordb
#
# June 2026 | Invariant Research

import logging
from typing import Any, Dict, List, Optional

from sigma_guard.adapters.base import GraphDatabaseAdapter, ContradictionError

logger = logging.getLogger(__name__)


class FalkorDBGuard(GraphDatabaseAdapter):
    """
    FalkorDB adapter for SIGMA pre-commit contradiction detection.

    Uses the FalkorDB Python client to connect to a FalkorDB
    instance and verify graph writes for structural contradictions.

    FalkorDB runs as a Redis module, so the connection uses the
    Redis protocol on the default port 6379.

    Usage:
        guard = FalkorDBGuard(
            host="localhost",
            port=6379,
            graph="knowledge",
        )
        guard.connect()
        guard.install_trigger()

        # Verified writes
        guard.execute("CREATE (a:Concept {name: 'dog'})-[:IsA]->(b:Concept {name: 'animal'})")

        # Scan existing graph
        result = guard.verify_current_graph()
        print(result)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        graph: str = "knowledge",
        stalk_dim: int = 8,
        seed: int = 42,
        block_on_contradiction: bool = True,
        log_only: bool = False,
        constraints: dict = None,
    ):
        super().__init__(
            stalk_dim=stalk_dim,
            seed=seed,
            block_on_contradiction=block_on_contradiction,
            log_only=log_only,
            constraints=constraints,
        )
        self.host = host
        self.port = port
        self.graph_name = graph
        self._db = None
        self._graph = None

    def connect(self, **kwargs) -> None:
        """Connect to FalkorDB via the Redis protocol."""
        try:
            from falkordb import FalkorDB
        except ImportError:
            raise ImportError(
                "falkordb driver required. Install with: pip install falkordb"
            )

        self._db = FalkorDB(
            host=kwargs.get("host", self.host),
            port=kwargs.get("port", self.port),
        )
        self._graph = self._db.select_graph(
            kwargs.get("graph", self.graph_name)
        )
        logger.info(
            "Connected to FalkorDB at %s:%d, graph '%s'",
            self.host, self.port, self.graph_name,
        )

    def install_trigger(self) -> None:
        """
        Load the current graph state into SIGMA for incremental checking.

        FalkorDB does not have native pre-commit hooks in the Python
        client. Writes are verified through guard.execute() which
        checks before committing. For server-side integration, use
        the FalkorDB module API.
        """
        if self._graph is None:
            self.connect()

        self._load_current_graph()
        logger.info(
            "FalkorDB graph '%s' loaded into SIGMA. "
            "Use guard.execute() for verified writes.",
            self.graph_name,
        )

    def execute(self, cypher: str, **params) -> Any:
        """
        Execute a Cypher query with pre-commit contradiction checking.

        For write queries (CREATE, SET, MERGE, DELETE), SIGMA verifies
        the operation before committing. Read queries pass through.

        Args:
            cypher: OpenCypher query string
            **params: Query parameters

        Returns:
            Query result
        """
        if self._graph is None:
            self.connect()

        upper = cypher.strip().upper()
        is_write = any(
            kw in upper
            for kw in ["CREATE", "SET", "MERGE", "DELETE", "REMOVE"]
        )

        if is_write:
            write_ops = self._parse_cypher_write(cypher, params)
            allowed = self.on_write(
                vertices=write_ops.get("vertices", []),
                edges=write_ops.get("edges", []),
                properties=write_ops.get("properties", []),
            )
            if not allowed:
                return None

        result = self._graph.query(cypher)

        if is_write:
            self._load_current_graph()

        return result

    def on_write(
        self,
        vertices: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        properties: List[Dict[str, Any]],
    ) -> bool:
        """Verify write operations for contradictions."""
        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
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

        self._write_count += 1
        return True

    def verify_current_graph(self):
        """Run full verification on the current FalkorDB graph."""
        if self._graph is None:
            self.connect()
        self._load_current_graph()
        return self.guard.verify()

    def _load_current_graph(self) -> None:
        """Load the current FalkorDB graph into SIGMA."""
        # Get all nodes
        node_result = self._graph.query(
            "MATCH (n) RETURN ID(n) AS id, labels(n) AS labels, "
            "properties(n) AS props"
        )
        vertices = []
        for row in node_result.result_set:
            node_id = row[0]
            labels = row[1] if row[1] else []
            label = labels[0] if labels else "node"
            props = row[2] if row[2] else {}
            # Use name property as display label if available
            display = props.get("name", props.get("title", label))
            vertices.append({
                "id": str(node_id),
                "label": str(display),
                "claims": dict(props) if props else {},
            })

        # Get all edges
        edge_result = self._graph.query(
            "MATCH (a)-[r]->(b) RETURN ID(a) AS src, ID(b) AS tgt, "
            "type(r) AS rel, properties(r) AS props"
        )
        edges = []
        for row in edge_result.result_set:
            edges.append({
                "source": str(row[0]),
                "target": str(row[1]),
                "relation": row[2],
                "value": dict(row[3]) if row[3] else {},
            })

        self.guard.load_dict({"vertices": vertices, "edges": edges})
        logger.info(
            "Loaded %d vertices, %d edges from FalkorDB graph '%s'",
            len(vertices), len(edges), self.graph_name,
        )

    def _parse_cypher_write(
        self, cypher: str, params: Dict
    ) -> Dict[str, List]:
        """
        Parse a Cypher write query to extract operations.

        LIMITATION: This is a best-effort regex parser for common
        CREATE patterns. It extracts relationship types and node
        labels where possible, but does not fully parse Cypher.
        Complex multi-clause queries, MERGE, or parameterized
        patterns may not be extracted accurately.

        For full server-side write interception, use the FalkorDB
        module API, which provides structured transaction metadata.

        When extraction fails, the write is still executed and the
        graph is reloaded afterward, so verify_current_graph()
        remains accurate. Only the pre-commit gate is weakened.
        """
        import re

        result = {"vertices": [], "edges": [], "properties": []}
        upper = cypher.upper()

        if "CREATE" in upper and "->" in cypher:
            # Try to extract: CREATE (a:Label)-[:REL]->(b:Label)
            edge_pattern = re.compile(
                r"\(\s*\w*\s*(?::([\w]+))?[^)]*\)"
                r"\s*-\[\s*\w*\s*:([\w]+)[^\]]*\]->\s*"
                r"\(\s*\w*\s*(?::([\w]+))?[^)]*\)"
            )
            match = edge_pattern.search(cypher)
            if match:
                src_label = match.group(1) or "unknown"
                rel_type = match.group(2) or "CREATED"
                tgt_label = match.group(3) or "unknown"
            else:
                src_label = "unknown"
                tgt_label = "unknown"
                rel_match = re.search(r"\[:([\w]+)", cypher)
                rel_type = rel_match.group(1) if rel_match else "CREATED"
            result["edges"].append({
                "source": src_label,
                "target": tgt_label,
                "relation": rel_type,
            })
        elif "CREATE" in upper:
            label_match = re.search(r"\(\s*\w*\s*:([\w]+)", cypher)
            label = label_match.group(1) if label_match else "unknown"
            result["vertices"].append({
                "label": label,
                "properties": params,
            })

        return result

    def close(self) -> None:
        """Close the FalkorDB connection."""
        self._db = None
        self._graph = None
