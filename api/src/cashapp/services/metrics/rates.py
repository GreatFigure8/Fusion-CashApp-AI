"""Rate and money helpers. An unmeasured rate is ``None``, never ``0.0``."""

from decimal import Decimal

from cashapp.domain.money import to_money


def rate(numerator: int, denominator: int) -> float | None:
    """``numerator / denominator`` in 0..1, or None when nothing was measured."""
    if denominator <= 0:
        return None
    return numerator / denominator


def money(value: Decimal) -> Decimal:
    """Two decimal places, ROUND_HALF_UP."""
    return to_money(value)
