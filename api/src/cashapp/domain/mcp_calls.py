"""Vocabulary of the MCP call log. Defined once; the recorder and the API import it."""

from enum import StrEnum


class McpCallOutcome(StrEnum):
    OK = "OK"
    ERROR = "ERROR"
    REFUSED = "REFUSED"  # refused before any call: write guard, SQL guard
