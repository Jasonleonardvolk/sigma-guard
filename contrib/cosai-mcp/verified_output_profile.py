"""Proposed addition to cosai-mcp built-in profiles: verified-output.

This profile is for MCP servers that produce SVR (Structural Verification
Receipt) receipts with tool outputs. All threat categories are enabled.
The T09-002 catalog probe checks for receipt presence in tool responses.

Integration: add this profile to cosai_mcp/profiles/builtin.py in the
BUILTIN_PROFILES registry.

Usage:
    cosai scan http://your-mcp-server --profile verified-output --auth-token $TOKEN
"""
from __future__ import annotations

import types

from cosai_mcp.profiles.models import ServerProfile


VERIFIED_OUTPUT = ServerProfile(
    name="verified-output",
    description=(
        "MCP server with structural verification on tool outputs. "
        "Expects SVR receipts attached to tool responses via _meta.svr_receipt "
        "or a dedicated get_receipt tool."
    ),
    mcp_path="/mcp",
    auth_header_format="Bearer {token}",
    tool_name_map=types.MappingProxyType({
        "verify_graph": "verify_graph",
        "verify_claims": "verify_claims",
        "check_write": "check_write",
    }),
    skip_categories=frozenset(),
    notes=(
        "Use for MCP servers that produce Structural Verification Receipts "
        "(SVR) with tool outputs. All threat categories are enabled including "
        "T09-002 (SVR receipt presence check). The tool_name_map seeds the "
        "three standard sigma-guard tool names. No categories are skipped; "
        "a verified-output server should pass the full threat battery."
    ),
)

# To register: add to the BUILTIN_PROFILES dict in builtin.py:
#
#   from cosai_mcp.contrib.verified_output_profile import VERIFIED_OUTPUT
#
#   BUILTIN_PROFILES = types.MappingProxyType({
#       ...existing profiles...,
#       VERIFIED_OUTPUT.name: VERIFIED_OUTPUT,
#   })
