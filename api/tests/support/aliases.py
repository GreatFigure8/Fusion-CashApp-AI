"""Test support for payer aliases: an unsaved-row factory and a fake ``AliasLookup``."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from cashapp.data.models.aliases import PayerAlias
from cashapp.services.aliases import AliasMatch


def make_payer_alias(**overrides: Any) -> PayerAlias:
    """An unsaved name alias for "acme" -> customer 10001 created by user u1."""
    fields: dict[str, Any] = {
        "payer_name_norm": "acme",
        "payer_bank_account": None,
        "reference_pattern": None,
        "customer_account_number": "10001",
        "learned_from_item_id": None,
        "created_by": "u1",
        "created_by_name": "Test User",
        "created_at": datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
        "uses": 0,
    }
    fields.update(overrides)
    return PayerAlias(**fields)


class FakeAliasLookup:
    """Satisfies ``AliasLookup``; returns a fixed match or one keyed by (name, bank account)."""

    def __init__(
        self,
        result: AliasMatch | Mapping[tuple[str | None, str | None], AliasMatch] | None = None,
    ) -> None:
        self._result = result if result is not None else AliasMatch()
        self.calls: list[tuple[str | None, str | None, tuple[str, ...]]] = []

    async def lookup(
        self, payer_name: str | None, bank_account: str | None, references: Sequence[str]
    ) -> AliasMatch:
        self.calls.append((payer_name, bank_account, tuple(references)))
        if isinstance(self._result, AliasMatch):
            return self._result
        return self._result.get((payer_name, bank_account), AliasMatch())
