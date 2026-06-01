# sigma_guard/adapters/__init__.py
from sigma_guard.adapters.base import GraphDatabaseAdapter

__all__ = ["GraphDatabaseAdapter"]

# Database adapters are imported on demand to avoid requiring
# database drivers as hard dependencies. Use:
#   from sigma_guard.adapters.neo4j import Neo4jGuard
#   from sigma_guard.adapters.memgraph import MemgraphGuard
#   from sigma_guard.adapters.falkordb import FalkorDBGuard
