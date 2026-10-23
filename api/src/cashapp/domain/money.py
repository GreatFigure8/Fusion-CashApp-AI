"""Money: Decimal end to end, 2 dp, ROUND_HALF_UP, always carrying its currency."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

import pydantic.dataclasses
from pydantic import BeforeValidator, PlainSerializer, StringConstraints, WithJsonSchema
from pydantic_core import PydanticCustomError

_CENT = Decimal("0.01")
_EQ_TOLERANCE = Decimal("0.005")


class CurrencyMismatchError(ValueError):
    """Arithmetic or comparison across two currencies."""


def to_money(value: Decimal | str | int) -> Decimal:
    """Quantise to 2 dp with ROUND_HALF_UP. Floats are refused: they carry binary error."""
    if isinstance(value, bool | float):
        raise TypeError("to_money does not accept float or bool; pass Decimal, str or int")
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def money_eq(a: Decimal, b: Decimal) -> bool:
    """Exact equality for money means within half a cent."""
    return abs(a - b) <= _EQ_TOLERANCE


def _coerce(value: Any) -> Decimal:
    # JSON input may arrive as a float; go through str so 2.675 stays 2.675.
    if isinstance(value, float):
        value = str(value)
    try:
        return to_money(value)
    except (TypeError, ArithmeticError, ValueError) as exc:
        raise PydanticCustomError("money_invalid", "Value is not a valid money amount") from exc


CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]

MoneyStr = Annotated[
    Decimal,
    BeforeValidator(_coerce),
    PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["12480.00"]}),
]


@pydantic.dataclasses.dataclass(frozen=True)
class Money:
    amount: MoneyStr
    currency: CurrencyCode

    def _check(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(f"{self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def eq(self, other: Money) -> bool:
        self._check(other)
        return money_eq(self.amount, other.amount)

    def is_zero(self) -> bool:
        return money_eq(self.amount, Decimal(0))

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(Decimal("0.00"), currency)
