# sigma_guard/adapters/base.py
# Abstract base class for graph database adapters.
#
# Implement this to integrate SIGMA with any graph database.
# The adapter translates database-specific write events into
# SIGMA verification calls.
#
# May 2026 | Invariant Research | Patent Pending

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from sigma_guard.engine import SigmaGuard
from sigma_guard.verdict import WriteCheckResult

logger = logging.getLogger(__name__)


class ContradictionError(Exception):
    """Raised when a write would create a structural contradiction."""

    def __init__(self, result: WriteCheckResult):
        self.result = result
        super().__init__(
            "Write blocked: %s (severity=%s, proof=%s)"
            % (result.explanation, result.severity, result.proof_id)
        )


class GraphDatabaseAdapter(ABC):
    """
    Abstract base class for graph database adapters.

    Subclasses implement connect(), install_trigger(), and on_write()
    for their specific database. The base class provides the SIGMA
    verification logic.

    Usage:
        class MyDBAdapter(GraphDatabaseAdapter):
            def connect(self, **kwargs):
                self.client = MyDBClient(**kwargs)

            def install_trigger(self):
                self.client.register_before_commit(self._handle_commit)

            def on_write(self, vertices, edges, properties):
                for edge in edges:
                    result = self.guard.check_write(
                        source=edge["source"],
                        target=edge["target"],
                        relation=edge.get("type", ""),
                    )
                    if result.creates_contradiction:
                        raise ContradictionError(result)
                return True
    """

    def __init__(
        self,
        stalk_dim: int = 8,
        seed: int = 42,
        block_on_contradiction: bool = True,
        log_only: bool = False,
    ):
        """
        Args:
            stalk_dim: Sheaf stalk dimension.
            seed: Random seed for reproducibility.
            block_on_contradiction: If True, reject writes that create
                contradictions. If False, log but allow.
            log_only: If True, log all verdicts but never block.
        """
        self.guard = SigmaGuard(stalk_dim=stalk_dim, seed=seed)
        self.block_on_contradiction = block_on_contradiction
        self.log_only = log_only
        self._write_count = 0
        self._blocked_count = 0

    @abstractmethod
    def connect(self, **kwargs) -> None:
        """Connect to the database."""
        ...

    @abstractmethod
    def install_trigger(self) -> None:
        """Register SIGMA as a pre-commit verification hook."""
        ...

    @abstractmethod
    def on_write(
        self,
        vertices: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        properties: List[Dict[str, Any]],
    ) -> bool:
        """
        Called before each write transaction.

        Args:
            vertices: New vertices being created
            edges: New edges being created
            properties: Properties being set/updated

        Returns:
            True to allow the write, False to reject it.

        Raises:
            ContradictionError if block_on_contradiction is True
            and the write would create a contradiction.
        """
        ...

    def _check_and_decide(self, result: WriteCheckResult) -> bool:
        """Check a write result and decide whether to allow it."""
        self._write_count += 1

        if not result.creates_contradiction:
            return True

        self._blocked_count += 1
        logger.warning(
            "SIGMA: Contradiction detected (severity=%s, energy_delta=%.4f). "
            "Write: %s",
            result.severity,
            result.energy_delta,
            result.explanation,
        )

        if self.log_only:
            return True

        if self.block_on_contradiction:
            raise ContradictionError(result)

        return False

    def stats(self) -> Dict[str, int]:
        """Return adapter statistics."""
        return {
            "writes_checked": self._write_count,
            "writes_blocked": self._blocked_count,
            "block_rate": (
                round(self._blocked_count / max(self._write_count, 1), 4)
            ),
        }

    def load_snapshot(self, path: str, fmt: str = "json") -> None:
        """Load an existing graph snapshot for incremental checking."""
        if fmt == "json":
            self.guard.load_json(path)
        elif fmt == "graphml":
            self.guard.load_graphml(path)
        elif fmt == "edges":
            self.guard.load_edge_list(path)
        else:
            raise ValueError("Unknown format: %s" % fmt)
