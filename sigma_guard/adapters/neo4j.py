# sigma_guard/adapters/neo4j.py
# Neo4j adapter: contradiction detection via transaction event handlers.
#
# Neo4j supports TransactionEventListener (Java) and Python driver
# managed transactions. SIGMA hooks into the Python driver's
# transaction lifecycle to verify writes before commit.
#
# Requirements:
#   pip install neo4j
#
# May 2026 | Invariant Research

import logging
from typing import Any, Dict, List, Optional

from sigma_guard.adapters.base import GraphDatabaseAdapter, ContradictionError

logger = logging.getLogger(__name__)


class Neo4jGuard(GraphDatabaseAdapter):
    """
    Neo4j adapter for SIGMA pre-commit contradiction detection.

    Uses the Neo4j Python driver to intercept write transactions
    and verify them for structural contradictions before commit.

    Usage:
        guard = Neo4jGuard(
            uri="bolt://localhost:7687",
            auth=("neo4j", "password"),
        )
        guard.install_transaction_listener()

        # All subsequent writes via guard.execute() are verified
        guard.execute("CREATE (a:Supplier {name: 'A', sole_source: true})")
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        auth: tuple = ("neo4j", "password"),
        database: str = "neo4j",
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
        self.uri = uri
        self.auth = auth
        self.database = database
        self._driver = None

    def connect(self, **kwargs) -> None:
        """Connect to Neo4j via the Bolt protocol."""
        try:
            from neo4j import GraphDatabase
        except ImportError:
            raise ImportError(
                "neo4j driver required. Install with: pip install neo4j"
            )

        self._driver = GraphDatabase.driver(
            kwargs.get("uri", self.uri),
            auth=kwargs.get("auth", self.auth),
        )
        # Verify connectivity
        self._driver.verify_connectivity()
        logger.info("Connected to Neo4j at %s", self.uri)

    def install_transaction_listener(self) -> None:
        """
        Load the current graph state into SIGMA for incremental checking.

        Note: Neo4j's TransactionEventListener is a Java API.
        For Python, we wrap write operations through guard.execute()
        which verifies before committing. For full server-side
        integration, deploy the SIGMA Java plugin.
        """
        if self._driver is None:
            self.connect()

        # Take snapshot of current graph
        self._load_current_graph()
        logger.info(
            "Neo4j graph loaded into SIGMA. Use guard.execute() for "
            "verified writes."
        )

    def install_trigger(self) -> None:
        """Alias for install_transaction_listener."""
        self.install_transaction_listener()

    def execute(self, cypher: str, **params) -> Any:
        """
        Execute a Cypher query with pre-commit contradiction checking.

        For write queries (CREATE, SET, MERGE, DELETE), SIGMA verifies
        the operation before committing. Read queries pass through.

        Args:
            cypher: Cypher query string
            **params: Query parameters

        Returns:
            Query result (list of records)

        Raises:
            ContradictionError if the write creates a contradiction
        """
        if self._driver is None:
            self.connect()

        # Detect write operations
        upper = cypher.strip().upper()
        is_write = any(
            kw in upper
            for kw in ["CREATE", "SET", "MERGE", "DELETE", "REMOVE"]
        )

        if is_write:
            # Parse the write to extract vertices/edges being created
            write_ops = self._parse_cypher_write(cypher, params)
            allowed = self.on_write(
                vertices=write_ops.get("vertices", []),
                edges=write_ops.get("edges", []),
                properties=write_ops.get("properties", []),
            )
            if not allowed:
                return []

        # Execute the query
        with self._driver.session(database=self.database) as session:
            result = session.run(cypher, **params)
            records = [dict(r) for r in result]

        # If it was a write, reload affected portion of graph
        if is_write:
            self._load_current_graph()

        return records

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
        """Run full verification on the current Neo4j graph."""
        if self._driver is None:
            self.connect()
        self._load_current_graph()
        return self.guard.verify()

    def _load_current_graph(self) -> None:
        """Load the current Neo4j graph into SIGMA."""
        with self._driver.session(database=self.database) as session:
            # Get vertices
            v_result = session.run(
                "MATCH (n) RETURN elementId(n) AS id, labels(n) AS labels, "
                "properties(n) AS props LIMIT 100000"
            )
            vertices = []
            for record in v_result:
                labels = record["labels"]
                label = labels[0] if labels else "node"
                props = dict(record["props"]) if record["props"] else {}
                # Use the name property as the display label if available,
                # falling back to the Neo4j node type label.
                display = props.get("name", props.get("title", label))
                vertices.append({
                    "id": str(record["id"]),
                    "label": str(display),
                    "claims": props,
                })

            # Get edges
            e_result = session.run(
                "MATCH (a)-[r]->(b) RETURN elementId(a) AS src, "
                "elementId(b) AS tgt, type(r) AS rel, "
                "properties(r) AS props LIMIT 100000"
            )
            edges = []
            for record in e_result:
                edges.append({
                    "source": str(record["src"]),
                    "target": str(record["tgt"]),
                    "relation": record["rel"],
                    "value": dict(record["props"]) if record["props"] else {},
                })

        self.guard.load_dict({"vertices": vertices, "edges": edges})

    def _parse_cypher_write(
        self, cypher: str, params: Dict
    ) -> Dict[str, List]:
        """
        Parse a Cypher write query to extract the operations.

        LIMITATION: This is a best-effort regex parser for common
        CREATE patterns. It extracts relationship types and node
        labels where possible, but does not fully parse Cypher.
        Complex multi-clause queries, MERGE, or parameterized
        patterns may not be extracted accurately.

        For full server-side write interception, deploy the SIGMA
        Neo4j Java plugin, which receives structured transaction
        metadata from the Neo4j kernel.

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
                # Try to extract at least the relation type
                rel_match = re.search(r"\[:([\w]+)", cypher)
                rel_type = rel_match.group(1) if rel_match else "CREATED"
            result["edges"].append({
                "source": src_label,
                "target": tgt_label,
                "relation": rel_type,
            })
        elif "CREATE" in upper:
            # Try to extract node label: CREATE (a:Label {...})
            label_match = re.search(r"\(\s*\w*\s*:([\w]+)", cypher)
            label = label_match.group(1) if label_match else "unknown"
            result["vertices"].append({
                "label": label,
                "properties": params,
            })

        return result

    def close(self) -> None:
        """Close the Neo4j driver."""
        if self._driver:
            self._driver.close()
            self._driver = None
