"""Typed errors for the fusion-sql-mcp (Greenlight) server, mapped onto the auto-fix error codes.

A tool failure arrives as the text of a `ToolError` (fusion-sql-mcp `rest_tools.py`, `rest.py`).
Only the status or the kind is kept; the text is clipped and never carries a request body.
"""

from __future__ import annotations

import re

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.errors import FusionError, error_from_http

__all__ = ["McpError", "error_from_tool_text", "transport_error"]

_MAX_TEXT = 160
_ANSWERED = re.compile(r"Fusion answered (\d{3})")
_NO_ANSWER = re.compile(r"No answer from the pod", re.IGNORECASE)
_WRITE_REFUSED = re.compile(r"Write-back is off|write allowlist", re.IGNORECASE)


class McpError(FusionError):
    """A failure of the MCP connection itself (not configured, unreachable, bad credentials)."""


def _clip(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _MAX_TEXT else flat[:_MAX_TEXT] + "..."


def transport_error(message: str, *, write: bool, certainly_not_sent: bool = False) -> McpError:
    """A transient transport failure. For a write the outcome is unknown unless nothing was sent."""
    return McpError(
        ErrorCode.FUSION_TRANSIENT,
        message,
        outcome_unknown=write and not certainly_not_sent,
    )


def error_from_tool_text(text: str, *, write: bool) -> FusionError:
    """Map the text of a server `ToolError` to a typed Fusion error."""
    answered = _ANSWERED.search(text)
    if answered is not None:
        error = error_from_http(int(answered.group(1)), text.encode("utf-8", errors="replace"))
        error.outcome_unknown = write and error.retryable
        return error
    if _NO_ANSWER.search(text):
        return McpError(
            ErrorCode.FUSION_TRANSIENT,
            "no answer from the Fusion pod",
            outcome_unknown=write,
        )
    if _WRITE_REFUSED.search(text):
        return McpError(
            ErrorCode.FUSION_WRITE_DISABLED,
            "the MCP server refused the write for this Fusion source",
            retryable=False,
        )
    return McpError(
        ErrorCode.FUSION_FAULT,
        f"MCP tool error: {_clip(text)}",
        retryable=False,
        outcome_unknown=False,
    )
