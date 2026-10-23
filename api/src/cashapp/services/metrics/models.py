"""Frozen result models of ``MetricsService``: the contracts the router, chat tool and reports use.

Money is ``MoneyStr`` (2 dp, ROUND_HALF_UP, a string in JSON) and always travels with its
currency. No model carries a money field that mixes currencies. A rate is a float in 0..1, and
``None`` means it was not measured (never ``0.0``).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.llm_usage import LlmRole
from cashapp.domain.metrics import ActivityKind, CostBasis, MetricsWindow
from cashapp.domain.money import CurrencyCode, MoneyStr


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class AwaitingReceipt(_Frozen):
    count: int
    oldest_age_days: int | None
    aging_limit_days: int


class OpenExceptions(_Frozen):
    total: int
    locked: int
    dead_lettered: int


class ProgressSummary(_Frozen):
    window: MetricsWindow
    start: datetime
    end: datetime
    receipts_matched: int
    done_items: int
    automation_rate: float | None
    awaiting_receipt: AwaitingReceipt
    open_exceptions: OpenExceptions
    autofix_rate: float | None
    human_correction_rate: float | None


class CurrencyTotal(_Frozen):
    currency: CurrencyCode
    amount: MoneyStr
    receipts: int
    residual: MoneyStr


class ThroughputPoint(_Frozen):
    at: datetime
    applied: int
    escalated: int


class AutofixOutcome(_Frozen):
    error_code: ErrorCode
    count: int
    fixed: int
    rate: float | None


class ModelEfficiencyRow(_Frozen):
    role: LlmRole
    model_id: str
    calls: int
    cost_basis: CostBasis
    cost_usd: MoneyStr | None
    cost_unknown_share: float | None
    agreement_rate: float | None
    human_correction_rate: float | None
    accuracy: float | None
    accuracy_n: int


class ActivityEvent(_Frozen):
    id: int
    at: datetime
    kind: ActivityKind
    item_id: int | None
    text: str
