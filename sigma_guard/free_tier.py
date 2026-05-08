# sigma_guard/free_tier.py
# Free tier enforcement for SIGMA Guard.
#
# The free tier allows unlimited use up to 10,000 vertices.
# Above 10,000 vertices, the engine returns an error directing
# the user to contact Invariant Research for a commercial license.
#
# This file is checked before every graph load operation.
# It is NOT a security boundary (the source is visible).
# It is a licensing reminder for honest users.
#
# May 2026 | Invariant Research

import os

# Free tier vertex limit. Override with SIGMA_VERTEX_LIMIT env var.
DEFAULT_VERTEX_LIMIT = 10_000

# Set to "1" to disable the limit (commercial license holders)
SIGMA_UNLIMITED = os.getenv("SIGMA_UNLIMITED", "0")


class FreeTierExceeded(Exception):
    """Raised when a graph exceeds the free tier vertex limit."""

    def __init__(self, vertex_count: int, limit: int):
        self.vertex_count = vertex_count
        self.limit = limit
        super().__init__(
            "Graph has %d vertices, which exceeds the free tier limit "
            "of %d. For production use above %d vertices, contact "
            "Invariant Research: https://invariant.pro/licensing"
            % (vertex_count, limit, limit)
        )


def check_free_tier(vertex_count: int) -> None:
    """
    Check whether the vertex count is within the free tier limit.

    Raises FreeTierExceeded if the limit is exceeded and no
    commercial license environment variable is set.
    """
    if SIGMA_UNLIMITED == "1":
        return

    limit = int(os.getenv("SIGMA_VERTEX_LIMIT", str(DEFAULT_VERTEX_LIMIT)))

    if vertex_count > limit:
        raise FreeTierExceeded(vertex_count, limit)


def get_tier_info() -> dict:
    """Return current tier information."""
    if SIGMA_UNLIMITED == "1":
        return {
            "tier": "commercial",
            "vertex_limit": None,
            "unlimited": True,
        }
    limit = int(os.getenv("SIGMA_VERTEX_LIMIT", str(DEFAULT_VERTEX_LIMIT)))
    return {
        "tier": "free",
        "vertex_limit": limit,
        "unlimited": False,
    }
