"""The ``report.json`` contract. Money is a string; a ratio over nothing has no rate."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict

from cashapp.evals.options import Suite
from cashapp.tools.anonymise.fixture_format import PriorLabel

__all__ = [
    "AutofixCaseResult",
    "AutofixSuiteReport",
    "CaseVariant",
    "ConfusionMatrix",
    "CostSummary",
    "EvalReport",
    "ExtractionCaseResult",
    "ExtractionSuiteReport",
    "LineScore",
    "MatchingCaseResult",
    "MatchingSuiteReport",
    "Ratio",
    "RoleCost",
    "SuiteStatus",
    "VariantName",
    "VariantScore",
]

type VariantName = Literal["reader_a", "reader_b", "adjudicated"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SuiteStatus(StrEnum):
    EVALUATED = "evaluated"
    NOT_EVALUATED = "not_evaluated"


class Ratio(_Model):
    correct: int
    total: int
    rate: float | None  # None when total == 0: nothing measured is never 100%

    @classmethod
    def of(cls, correct: int, total: int) -> Self:
        return cls(correct=correct, total=total, rate=(correct / total) if total else None)


class LineScore(_Model):
    expected: int
    predicted: int
    true_positive: int
    precision: float | None
    recall: float | None
    f1: float | None
    amount_correct: int
    kind_correct: int
    missing: list[str]
    extra: list[str]


class CaseVariant(_Model):
    fields: dict[str, bool]
    lines: LineScore
    fee_lines_ok: bool
    error_code: str | None


class VariantScore(_Model):
    fields: dict[str, Ratio]
    lines: LineScore
    line_amount: Ratio  # over matched lines
    line_kind: Ratio  # over matched lines
    fee_lines: Ratio
    failures: int


class ExtractionCaseResult(_Model):
    case_id: str
    run: int
    variants: dict[VariantName, CaseVariant]
    missing_reader: Literal["A", "B"] | None
    grounding_violations: list[str]
    disagreements: int
    adjudication_confidence: float | None


class ConfusionMatrix(_Model):
    rows: list[str]
    cols: list[str]
    counts: list[list[int]]


class ExtractionSuiteReport(_Model):
    status: SuiteStatus
    reason: str | None
    cases: int
    runs: int
    by_variant: dict[str, VariantScore]
    per_case: list[ExtractionCaseResult]


class MatchingCaseResult(_Model):
    message_id: str
    label: PriorLabel | None
    outcome: str
    error_code: str | None
    receipt_id: int | None
    candidates: int
    agrees: bool | None  # None when the message has no AR label


class MatchingSuiteReport(_Model):
    status: SuiteStatus
    reason: str | None
    messages: int
    labelled: int
    label_confusion: ConfusionMatrix
    label_agreement: Ratio  # agreement with AR's labels, not accuracy
    agreement_by_label: dict[str, Ratio]
    line_status_agreement: Ratio
    line_status_confusion: ConfusionMatrix
    skipped: dict[str, int]
    per_case: list[MatchingCaseResult]


class AutofixCaseResult(_Model):
    message_id: str
    label: PriorLabel
    error_code: str | None
    decisions: list[str]
    expected: str
    agrees: bool


class AutofixSuiteReport(_Model):
    status: SuiteStatus
    reason: str | None
    cases: int
    agreement: Ratio
    agreement_by_label: dict[str, Ratio]
    confusion: ConfusionMatrix
    codes_seen: dict[str, int]
    skipped: dict[str, int]
    per_case: list[AutofixCaseResult]


class RoleCost(_Model):
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: str | None  # None when some call could not be priced


class CostSummary(_Model):
    mode: Literal["live", "replay"]
    calls: int
    input_tokens: int
    output_tokens: int
    spent_usd: str
    recorded_usage_usd: str
    by_role: dict[str, RoleCost]
    by_model: dict[str, RoleCost]
    unknown_price_models: list[str]


class EvalReport(_Model):
    run_id: str
    started_at: datetime
    finished_at: datetime
    cashapp_version: str
    suites: list[Suite]
    limit: int | None
    runs: int
    replay: bool
    config_overrides: dict[str, Any]
    models: dict[str, str]
    prompt_versions: dict[str, str]
    cost: CostSummary
    extraction: ExtractionSuiteReport | None = None
    matching: MatchingSuiteReport | None = None
    autofix: AutofixSuiteReport | None = None
