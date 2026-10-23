"""Pure scoring: gold against one extraction, and the aggregation of those scores.

Strings compare after normalisation, amounts with ``money_eq`` (within half a cent), dates exactly.
Transaction numbers keep their suffix: ``2598014`` and ``2598014-1`` are different documents. A
variant that produced nothing (``actual is None``) gets every scored field wrong and recall 0, so
a model that refuses can never look accurate.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Final, cast

from cashapp.domain.extraction import ExtractedLine, LineKind, RemittanceExtraction
from cashapp.domain.money import money_eq
from cashapp.evals.gold import GoldExpected, GoldLine
from cashapp.evals.models import CaseVariant, ConfusionMatrix, LineScore, Ratio, VariantScore
from cashapp.services.aliases import normalise_bank_account, normalise_payer_name

__all__ = [
    "FEE_KINDS",
    "TRANSACTION_KINDS",
    "ConfusionCounter",
    "aggregate_variant",
    "normalise_ref",
    "score_fee_lines",
    "score_fields",
    "score_lines",
]

TRANSACTION_KINDS: Final = frozenset({LineKind.INVOICE, LineKind.CREDIT_MEMO, LineKind.UNKNOWN})
FEE_KINDS: Final = frozenset({LineKind.BANK_FEE, LineKind.TARIFF, LineKind.DISCOUNT})

# Header fields in report order. ``lines`` is scored separately.
FIELD_NAMES: Final[tuple[str, ...]] = (
    "payer_name",
    "payer_bank_account",
    "remittance_reference",
    "payment_amount",
    "currency",
    "currency_ambiguous",
    "payment_date",
    "dates",
    "bank_fees",
    "po_refs",
)


def normalise_ref(value: str | None) -> str | None:
    """Strip, upper-case and collapse inner whitespace. Suffixes such as ``-1`` are kept."""
    if value is None:
        return None
    return " ".join(value.split()).upper()


def _ref(value: str | None) -> str:
    return normalise_ref(value) or ""


def _money_multiset_equal(expected: Sequence[Decimal], actual: Sequence[Decimal]) -> bool:
    if len(expected) != len(actual):
        return False
    return all(money_eq(a, b) for a, b in zip(sorted(expected), sorted(actual), strict=True))


def _money_equal(expected: Decimal | None, actual: Decimal | None) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    return money_eq(expected, actual)


def _actual_value(name: str, extraction: RemittanceExtraction) -> object:
    match name:
        case "payer_name":
            return extraction.payer_name.value
        case "payer_bank_account":
            return extraction.payer_bank_account.value
        case "remittance_reference":
            return extraction.remittance_reference.value
        case "payment_amount":
            return extraction.payment_amount.value
        case "currency":
            return extraction.currency.value
        case "currency_ambiguous":
            return extraction.currency_ambiguous
        case "payment_date":
            return extraction.payment_date.value
        case "dates":
            return sorted({c.value for c in extraction.dates})
        case "bank_fees":
            return [fee.amount for fee in extraction.bank_fees]
        case "po_refs":
            return sorted({_ref(ref) for ref in extraction.po_refs})
        case _:
            raise KeyError(name)


def _field_correct(name: str, expected: object, actual: object) -> bool:
    match name:
        case "payer_name":
            return normalise_payer_name(_as_str(expected)) == normalise_payer_name(_as_str(actual))
        case "payer_bank_account":
            return normalise_bank_account(_as_str(expected)) == normalise_bank_account(
                _as_str(actual)
            )
        case "remittance_reference":
            return _ref(_as_str(expected)) == _ref(_as_str(actual))
        case "payment_amount":
            return _money_equal(_as_decimal(expected), _as_decimal(actual))
        case "currency":
            return _upper(_as_str(expected)) == _upper(_as_str(actual))
        case "currency_ambiguous":
            return bool(expected) == bool(actual)
        case "payment_date":
            return _as_date(expected) == _as_date(actual)
        case "dates":
            return set(_as_dates(expected)) == set(_as_dates(actual))
        case "bank_fees":
            return _money_multiset_equal(_as_decimals(expected), _as_decimals(actual))
        case "po_refs":
            return {_ref(r) for r in _as_strs(expected)} == {_ref(r) for r in _as_strs(actual)}
        case _:
            raise KeyError(name)


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _upper(value: str | None) -> str | None:
    return value.strip().upper() if value else None


def _as_decimal(value: object) -> Decimal | None:
    return value if isinstance(value, Decimal) else None


def _as_date(value: object) -> date | None:
    return value if isinstance(value, date) else None


def _items(value: object) -> list[object]:
    return list(cast("list[object]", value)) if isinstance(value, list) else []


def _as_dates(value: object) -> list[date]:
    return [v for v in _items(value) if isinstance(v, date)]


def _as_decimals(value: object) -> list[Decimal]:
    return [v for v in _items(value) if isinstance(v, Decimal)]


def _as_strs(value: object) -> list[str]:
    return [v for v in _items(value) if isinstance(v, str)]


def score_fields(expected: GoldExpected, actual: RemittanceExtraction | None) -> dict[str, bool]:
    """Correct or not, for each header field the gold file states (omitted fields are skipped).

    An explicit ``null`` states that the value must be absent. With no extraction every stated
    field is wrong.
    """
    scored: dict[str, bool] = {}
    for name in FIELD_NAMES:
        if name not in expected.model_fields_set:
            continue
        if actual is None:
            scored[name] = False
            continue
        scored[name] = _field_correct(name, getattr(expected, name), _actual_value(name, actual))
    return scored


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    total = precision + recall
    return 2 * precision * recall / total if total else 0.0


def _transaction_lines(lines: Sequence[ExtractedLine]) -> list[ExtractedLine]:
    return [ln for ln in lines if ln.kind in TRANSACTION_KINDS and ln.transaction_number.strip()]


def score_lines(expected: Sequence[GoldLine], actual: RemittanceExtraction | None) -> LineScore:
    """Precision, recall and F1 on the multiset of normalised transaction numbers.

    Amount and kind accuracy are counted over the matched lines only. Fee, tariff and discount
    lines are excluded here (see ``score_fee_lines``).
    """
    wanted = [g for g in expected if g.kind in TRANSACTION_KINDS and g.transaction_number.strip()]
    got = _transaction_lines(actual.lines) if actual is not None else []

    pool: dict[str, list[ExtractedLine]] = {}
    for line in got:
        pool.setdefault(_ref(line.transaction_number), []).append(line)

    true_positive = amount_correct = kind_correct = 0
    missing: list[str] = []
    for gold in wanted:
        key = _ref(gold.transaction_number)
        candidates = pool.get(key)
        if not candidates:
            missing.append(key)
            continue
        line = candidates.pop(0)
        true_positive += 1
        if _money_equal(gold.amount_paid, line.amount_paid):
            amount_correct += 1
        if gold.kind == line.kind:
            kind_correct += 1
    extra = sorted(
        key
        for remaining in pool.values()
        for key in [_ref(r.transaction_number) for r in remaining]
    )

    precision = _ratio(true_positive, len(got))
    recall = _ratio(true_positive, len(wanted))
    return LineScore(
        expected=len(wanted),
        predicted=len(got),
        true_positive=true_positive,
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        amount_correct=amount_correct,
        kind_correct=kind_correct,
        missing=missing,
        extra=extra,
    )


def score_fee_lines(expected: Sequence[GoldLine], actual: RemittanceExtraction | None) -> bool:
    """Fee, tariff and discount lines: the same count and the same multiset of amounts."""
    if actual is None:
        return False
    wanted = [g.amount_paid for g in expected if g.kind in FEE_KINDS]
    got = [ln.amount_paid for ln in actual.lines if ln.kind in FEE_KINDS]
    if len(wanted) != len(got):
        return False
    known_wanted = [a for a in wanted if a is not None]
    known_got = [a for a in got if a is not None]
    return len(known_wanted) == len(known_got) and _money_multiset_equal(known_wanted, known_got)


def _sum_lines(scores: Sequence[LineScore]) -> LineScore:
    expected = sum(s.expected for s in scores)
    predicted = sum(s.predicted for s in scores)
    true_positive = sum(s.true_positive for s in scores)
    precision = _ratio(true_positive, predicted)
    recall = _ratio(true_positive, expected)
    return LineScore(
        expected=expected,
        predicted=predicted,
        true_positive=true_positive,
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        amount_correct=sum(s.amount_correct for s in scores),
        kind_correct=sum(s.kind_correct for s in scores),
        missing=[m for s in scores for m in s.missing],
        extra=[e for s in scores for e in s.extra],
    )


def aggregate_variant(variants: Sequence[CaseVariant]) -> VariantScore:
    """Totals over every case and run of one variant (reader A, reader B or adjudicated)."""
    correct: Counter[str] = Counter()
    total: Counter[str] = Counter()
    for variant in variants:
        for name, ok in variant.fields.items():
            total[name] += 1
            correct[name] += int(ok)
    lines = _sum_lines([v.lines for v in variants])
    return VariantScore(
        fields={name: Ratio.of(correct[name], total[name]) for name in FIELD_NAMES if total[name]},
        lines=lines,
        line_amount=Ratio.of(lines.amount_correct, lines.true_positive),
        line_kind=Ratio.of(lines.kind_correct, lines.true_positive),
        fee_lines=Ratio.of(sum(int(v.fee_lines_ok) for v in variants), len(variants)),
        failures=sum(1 for v in variants if v.error_code is not None),
    )


class ConfusionCounter:
    """A confusion matrix with fixed row and column labels."""

    def __init__(self, rows: Sequence[str], cols: Sequence[str]) -> None:
        self._rows = list(rows)
        self._cols = list(cols)
        self._counts = [[0] * len(self._cols) for _ in self._rows]

    def add(self, row: str, col: str) -> None:
        self._counts[self._rows.index(row)][self._cols.index(col)] += 1

    def to_model(self) -> ConfusionMatrix:
        return ConfusionMatrix(
            rows=list(self._rows), cols=list(self._cols), counts=[list(r) for r in self._counts]
        )
