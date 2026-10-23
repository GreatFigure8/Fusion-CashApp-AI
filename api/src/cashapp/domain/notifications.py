"""The notification event: what the system tells people about. Pure; no pipeline imports.

Delivery (email, chat) is s42's job. Sources only emit a ``NotifyEvent`` through the outbox.
"""

from enum import StrEnum
from typing import Annotated, Final, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from cashapp.domain.clock import Clock
from cashapp.domain.error_codes import ErrorCode

NOTIFY_TOPIC_NAME: Final = "notify"
"""``TopicNamer.named("notify")`` gives ``{prefix}.{env}.notify``."""

SUMMARY_MAX: Final = 2000


class NotifyKind(StrEnum):
    ITEM_ESCALATED = "item_escalated"
    DLQ_GROWTH = "dlq_growth"
    OUTAGE = "outage"
    BUDGET_EXCEEDED = "budget_exceeded"


class NotifySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class NotifyEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_id: UUID = Field(default_factory=uuid4)
    kind: NotifyKind
    severity: NotifySeverity
    work_item_id: int | None = None
    error_code: ErrorCode | None = None
    summary: Annotated[str, Field(min_length=1, max_length=SUMMARY_MAX)]
    occurred_at: AwareDatetime

    @classmethod
    def new(
        cls,
        kind: NotifyKind,
        severity: NotifySeverity,
        summary: str,
        *,
        clock: Clock,
        work_item_id: int | None = None,
        error_code: ErrorCode | None = None,
    ) -> Self:
        return cls(
            kind=kind,
            severity=severity,
            summary=summary[:SUMMARY_MAX],
            work_item_id=work_item_id,
            error_code=error_code,
            occurred_at=clock.now(),
        )
