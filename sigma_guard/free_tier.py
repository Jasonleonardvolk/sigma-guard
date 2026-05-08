# sigma_guard/free_tier.py
# Free tier enforcement for SIGMA Guard.
#
# Free tier: 10,000 vertices / 100,000 edges
# A vertex is any graph node submitted for verification.
# An edge is any relationship between two vertices.
#
# Override with environment variables:
#   SIGMA_VERTEX_LIMIT=250000
#   SIGMA_EDGE_LIMIT=2500000
#   SIGMA_UNLIMITED=1  (disables all limits)
#
# May 2026 | Invariant Research

import os

DEFAULT_VERTEX_LIMIT = 10_000
DEFAULT_EDGE_LIMIT = 100_000

SIGMA_UNLIMITED = os.getenv("SIGMA_UNLIMITED", "0")


class FreeTierExceeded(Exception):
    """Raised when a graph exceeds the free tier limits."""

    def __init__(self, message: str):
        super().__init__(message)


def check_free_tier(vertex_count: int, edge_count: int = 0) -> None:
    """
    Check whether the graph is within the free tier limits.

    Args:
        vertex_count: Number of vertices in the graph.
        edge_count: Number of edges in the graph.

    Raises:
        FreeTierExceeded if either limit is exceeded and no
        commercial license environment variable is set.
    """
    if SIGMA_UNLIMITED == "1":
        return

    v_limit = int(os.getenv("SIGMA_VERTEX_LIMIT", str(DEFAULT_VERTEX_LIMIT)))
    e_limit = int(os.getenv("SIGMA_EDGE_LIMIT", str(DEFAULT_EDGE_LIMIT)))

    if vertex_count > v_limit:
        raise FreeTierExceeded(
            "Graph has %d vertices (limit: %d). "
            "Free tier: up to %d vertices / %d edges. "
            "Production license: https://invariant.pro/licensing"
            % (vertex_count, v_limit, v_limit, e_limit)
        )

    if edge_count > 0 and edge_count > e_limit:
        raise FreeTierExceeded(
            "Graph has %d edges (limit: %d). "
            "Free tier: up to %d vertices / %d edges. "
            "Production license: https://invariant.pro/licensing"
            % (edge_count, e_limit, v_limit, e_limit)
        )


def get_tier_info() -> dict:
    """Return current tier information."""
    if SIGMA_UNLIMITED == "1":
        return {
            "tier": "commercial",
            "vertex_limit": None,
            "edge_limit": None,
            "unlimited": True,
        }
    return {
        "tier": "free",
        "vertex_limit": int(os.getenv("SIGMA_VERTEX_LIMIT", str(DEFAULT_VERTEX_LIMIT))),
        "edge_limit": int(os.getenv("SIGMA_EDGE_LIMIT", str(DEFAULT_EDGE_LIMIT))),
        "unlimited": False,
    }
