"""The model price table and the one cost function (s24 reuses both).

Prices are code: dated, sourced, and re-checked against the claude-api skill when changed. A usage
row stores the cost at the time of the call, so history is never re-priced. An unknown model has
no price: cost is ``None`` (and one warning per model id per process), never a made-up zero.
Fable models are never priced or allowed (they need 30-day retention).
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Literal

from cashapp.domain.llm_usage import to_usd
from cashapp.integrations.llm.base import LlmUsage

__all__ = [
    "PRICES",
    "PRICES_AS_OF",
    "PRICES_SOURCE",
    "ModelPrice",
    "compute_cost",
    "cost_of_usage",
]

logger = logging.getLogger(__name__)

_MILLION = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD per million tokens. ``dedicated`` models are billed per cluster-hour: 0 per call."""

    input_per_mtok: Decimal = Decimal(0)
    output_per_mtok: Decimal = Decimal(0)
    long_context_threshold: int | None = None
    long_input_per_mtok: Decimal | None = None
    long_output_per_mtok: Decimal | None = None
    billing: Literal["per_token", "dedicated"] = "per_token"


PRICES_AS_OF: Final = date(2026, 10, 23)
PRICES_SOURCE: Final = (
    "claude-api skill model table (cached 2026-10-06), first-party Claude API rates"
)
PRICES: Final[Mapping[str, ModelPrice]] = MappingProxyType(
    {
        "claude-opus-5-5": ModelPrice(
            input_per_mtok=Decimal("4.00"), output_per_mtok=Decimal("20.00")
        ),
        "claude-haiku-5-5": ModelPrice(
            input_per_mtok=Decimal("0.10"),
            output_per_mtok=Decimal("0.50"),
            long_context_threshold=100_000,
            long_input_per_mtok=Decimal("0.50"),
            long_output_per_mtok=Decimal("2.50"),
        ),
        # Dedicated AI cluster, billed per cluster-hour: its cost is tracked as utilisation.
        "cohere.command-a-vision": ModelPrice(billing="dedicated"),
    }
)

_warned: set[str] = set()


def compute_cost(
    model_id: str, input_tokens: int | None, output_tokens: int | None
) -> Decimal | None:
    """USD cost of one call at 6 dp (ROUND_HALF_UP), or ``None`` when it cannot be priced."""
    if input_tokens is None or output_tokens is None:
        return None
    price = PRICES.get(model_id)
    if price is None:
        if model_id not in _warned:
            _warned.add(model_id)
            logger.warning("llm_price_unknown", extra={"model_id": model_id})
        return None
    if price.billing == "dedicated":
        return to_usd(0)
    in_rate, out_rate = price.input_per_mtok, price.output_per_mtok
    if (
        price.long_context_threshold is not None
        and input_tokens > price.long_context_threshold
        and price.long_input_per_mtok is not None
        and price.long_output_per_mtok is not None
    ):
        in_rate, out_rate = price.long_input_per_mtok, price.long_output_per_mtok
    return to_usd((input_tokens * in_rate + output_tokens * out_rate) / _MILLION)


def cost_of_usage(usage: LlmUsage) -> Decimal | None:
    return compute_cost(usage.model_id, usage.input_tokens, usage.output_tokens)
