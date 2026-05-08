# sigma_guard/__init__.py
# SIGMA Graph Guard: Pre-commit contradiction detection for graph databases.
#
# Usage:
#   from sigma_guard import SigmaGuard
#   guard = SigmaGuard()
#   guard.load_json("my_graph.json")
#   verdict = guard.verify()
#
# May 2026 | Invariant Research | Patent Pending (U.S. App# 19/649,080)

from sigma_guard.engine import SigmaGuard
from sigma_guard.verdict import Verdict, Contradiction, WriteCheckResult

__version__ = "0.1.0"

__all__ = [
    "SigmaGuard",
    "Verdict",
    "Contradiction",
    "WriteCheckResult",
]
