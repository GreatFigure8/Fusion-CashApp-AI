"""The gold set: what a correct extraction of each fixture artifact contains.

A field left out of ``expected`` is not scored. A field present with ``null`` (or an empty list)
means the value must be absent, which is how the negative cases are written: a bare ``$`` must
not be resolved to a dollar, an invented bank fee must not appear.
"""

from datetime import date
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cashapp.domain.extraction import LineKind
from cashapp.domain.money import CurrencyCode, MoneyStr

__all__ = ["GoldCase", "GoldExpected", "GoldLine", "load_gold"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldLine(_Strict):
    kind: LineKind
    transaction_number: str
    amount_paid: MoneyStr | None = None


class GoldExpected(_Strict):
    """Every header field is optional; ``model_fields_set`` decides what is scored."""

    payer_name: str | None = None
    payer_bank_account: str | None = None
    remittance_reference: str | None = None
    payment_amount: MoneyStr | None = None
    currency: CurrencyCode | None = None
    currency_ambiguous: bool | None = None
    payment_date: date | None = None
    dates: list[date] | None = None
    bank_fees: list[MoneyStr] | None = None
    po_refs: list[str] | None = None
    lines: Annotated[list[GoldLine], Field(default_factory=list)]


class GoldCase(_Strict):
    case_id: str
    synthetic: bool
    artifact: str  # file name under the artifacts directory
    tags: list[str] = Field(default_factory=list)
    expected: GoldExpected


def load_gold(directory: Path) -> list[GoldCase]:
    """Every ``*.json`` in ``directory``, sorted by case id. A missing directory is an empty set.

    Raises ``ValueError`` naming the file when one does not validate.
    """
    if not directory.is_dir():
        return []
    cases: list[GoldCase] = []
    for path in sorted(directory.glob("*.json")):
        try:
            case = GoldCase.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, OSError, ValueError) as exc:
            # The pydantic message can quote input values; name the file and the error count only.
            detail = (
                f"{exc.error_count()} validation errors"
                if isinstance(exc, ValidationError)
                else type(exc).__name__
            )
            raise ValueError(f"invalid gold file {path.name}: {detail}") from None
        if case.case_id != path.stem:
            raise ValueError(f"invalid gold file {path.name}: case_id must equal the file name")
        cases.append(case)
    return sorted(cases, key=lambda c: c.case_id)
