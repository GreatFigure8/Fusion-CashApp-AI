"""JSON helpers shared by the Fusion and MCP integrations."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

__all__ = ["loads_decimal"]


def loads_decimal(content: bytes | str) -> Any:
    """Parse JSON with every non-integer number as `Decimal`; money never passes through float."""
    return json.loads(content, parse_float=Decimal)
