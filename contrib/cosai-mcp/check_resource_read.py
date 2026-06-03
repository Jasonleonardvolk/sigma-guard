"""Proposed addition to CoSAIStack: check_resource_read().

Closes the resources/read audit gap identified in THREAT_CATALOG.md:

    "Context retrieval via resources/read is an MCP-layer event that
     cosai-mcp middleware currently does not log. Adding it would close
     the middle segment of the causal chain (prompt_hash -> context_refs
     -> tool invocation)."

This method follows the same pattern as check_tool_call() and
check_response(): it logs the event to the AuditLogger when one is
configured, and does not raise.

Integration: add this method to CoSAIStack in
cosai_mcp/middleware/__init__.py alongside the existing check methods.

Usage:

    stack = CoSAIStack(audit_logger=AuditLogger("/var/log/cosai/audit.jsonl"))

    # After resources/read returns content
    stack.check_resource_read(
        uri="file:///workspace/config.yaml",
        session_id="ses-abc",
        parent_id=tool_call_entry_id,  # links to the DAG
    )

The parent_id parameter enables DAG construction: when a tool call
triggers a resource read, the resource read entry links back to the
tool call entry via parent_id. This closes the middle segment of
the causal chain that the THREAT_CATALOG.md identifies as a gap.
"""
from __future__ import annotations

from typing import Any


def check_resource_read(
    self: Any,
    uri: str,
    session_id: str = "unknown",
    parent_id: str | None = None,
) -> str | None:
    """Log a resources/read call for T12 audit completeness.

    Parameters
    ----------
    uri:
        The resource URI being read (e.g. "file:///workspace/data.csv").
    session_id:
        The MCP session identifier.
    parent_id:
        entry_id of the parent tool call (for DAG edge construction).
        When a tool call triggers a resource read, pass the tool call's
        audit entry_id here so the execution trace links them.

    Returns
    -------
    str or None
        The audit entry_id if logged, None if no audit logger is configured.
        The returned entry_id can be used as parent_id for subsequent
        child calls.
    """
    if self.audit is not None:
        return self.audit.log(
            method="resources/read",
            session_id=session_id,
            params={"uri": uri},
            parent_id=parent_id,
        )
    return None


# -----------------------------------------------------------------
# How to integrate into cosai_mcp/middleware/__init__.py
# -----------------------------------------------------------------
#
# Add the following import-time attribute and method to CoSAIStack:
#
#     # ----------------------------------------------------------------
#     # Resource read checks -- call after resources/read
#     # ----------------------------------------------------------------
#
#     def check_resource_read(
#         self, uri: str, session_id: str = "unknown",
#         parent_id: str | None = None,
#     ) -> str | None:
#         """Log a resources/read call for T12 audit completeness.
#
#         Closes the resources/read audit gap identified in
#         THREAT_CATALOG.md. The returned entry_id can be used as
#         parent_id for child calls, enabling DAG construction across
#         the context retrieval segment of the causal chain.
#         """
#         if self.audit is not None:
#             return self.audit.log(
#                 method="resources/read",
#                 session_id=session_id,
#                 params={"uri": uri},
#                 parent_id=parent_id,
#             )
#         return None
#
# The CoSAIStack docstring should be updated to show four check points:
#
#     Manifest-time (tools/list):
#       supply_chain (T11) + tool poisoning detection (T4)
#
#     Per-request (tools/call):
#       validation (T3) -> authz (T2) -> session (T7) -> audit (T12)
#
#     Response-time (tools/call response):
#       response boundary guard (T4/T9)
#
#     Context retrieval (resources/read):
#       audit (T12)
#
# -----------------------------------------------------------------
# Test case (for tests/middleware/test_cosai_stack.py)
# -----------------------------------------------------------------

def test_check_resource_read_logs_to_audit(tmp_path):
    """check_resource_read() logs uri and parent_id to audit chain."""
    from cosai_mcp.middleware import CoSAIStack
    from cosai_mcp.middleware.audit import AuditLogger

    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)
    stack = CoSAIStack(audit_logger=logger)

    # Simulate: tool call logged first, resource read as child
    tool_entry_id = logger.log(
        method="tools/call",
        session_id="ses-test",
        params={"tool": "fetch_config", "args": {}},
    )

    resource_entry_id = stack.check_resource_read(
        uri="file:///workspace/config.yaml",
        session_id="ses-test",
        parent_id=tool_entry_id,
    )

    assert resource_entry_id is not None

    entries = logger.entries()
    assert len(entries) == 2

    resource_entry = entries[1]
    assert resource_entry.method == "resources/read"
    assert resource_entry.parent_id == tool_entry_id
    assert resource_entry.session_id == "ses-test"

    # Verify DAG links correctly
    from cosai_mcp.middleware.audit import build_dag
    dag = build_dag(entries)
    children_of_tool_call = dag.get(tool_entry_id, [])
    assert len(children_of_tool_call) == 1
    assert children_of_tool_call[0].entry_id == resource_entry_id


def test_check_resource_read_no_logger():
    """check_resource_read() returns None when no logger configured."""
    from cosai_mcp.middleware import CoSAIStack

    stack = CoSAIStack()  # no audit_logger
    result = stack.check_resource_read(
        uri="file:///workspace/data.csv",
        session_id="ses-test",
    )
    assert result is None
