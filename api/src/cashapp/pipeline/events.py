"""The event contract, topic names and the one way anything is emitted: the transactional outbox."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from cashapp.data.hooks import after_commit
from cashapp.data.models.outbox import OutboxMessage
from cashapp.data.types import to_jsonable
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.stages import Stage
from cashapp.domain.work_item import PRIORITY_LIVE
from cashapp.pipeline.errors import MalformedEvent
from cashapp.pipeline.relay import outbox_signal
from cashapp.settings import StreamingSettings, get_settings

EVENT_SCHEMA_VERSION: Final = 1

TopicKind = Literal["main", "retry", "dlq"]

_KIND_SUFFIX: Final[Mapping[str, str]] = {"main": "", "retry": ".retry", "dlq": ".dlq"}


class StageEvent(BaseModel):
    """ "Item X is ready for stage Y". The database holds the state; the bus only carries this."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_id: UUID = Field(default_factory=uuid4)
    work_item_id: int
    stage: Stage
    attempt: int = Field(default=0, ge=0)
    not_before: AwareDatetime | None = None
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    emitted_at: AwareDatetime

    @classmethod
    def new(
        cls,
        work_item_id: int,
        stage: Stage,
        *,
        clock: Clock,
        attempt: int = 0,
        trace_id: str | None = None,
        not_before: datetime | None = None,
    ) -> Self:
        return cls(
            work_item_id=work_item_id,
            stage=stage,
            attempt=attempt,
            not_before=not_before,
            trace_id=trace_id if trace_id is not None else uuid4().hex,
            emitted_at=clock.now(),
        )


def parse_event(raw: bytes) -> StageEvent:
    """Parse bus bytes; an unknown schema version or any invalid field is a ``MalformedEvent``."""
    try:
        return StageEvent.model_validate_json(raw)
    except ValidationError as exc:
        raise MalformedEvent(f"{len(exc.errors())} validation error(s)") from exc


@dataclass(frozen=True, slots=True)
class TopicNamer:
    prefix: str
    env: str

    @classmethod
    def from_settings(cls, streaming: StreamingSettings) -> Self:
        return cls(prefix=streaming.topic_prefix, env=streaming.topic_env)

    def for_stage(self, stage: Stage, kind: TopicKind = "main") -> str:
        return f"{self.prefix}.{self.env}.{stage.value.lower()}{_KIND_SUFFIX[kind]}"

    def named(self, name: str) -> str:
        """A non-stage topic, for example ``notify``."""
        return f"{self.prefix}.{self.env}.{name}"


_default_namer: TopicNamer | None = None


def default_namer() -> TopicNamer:
    global _default_namer
    if _default_namer is None:
        _default_namer = TopicNamer.from_settings(get_settings().streaming)
    return _default_namer


def set_default_namer(namer: TopicNamer | None) -> None:
    """Tests and workers pin the namer; ``None`` clears the cache."""
    global _default_namer
    _default_namer = namer


def topic_for(stage: Stage, kind: TopicKind = "main") -> str:
    return default_namer().for_stage(stage, kind)


async def enqueue(
    uow: UnitOfWork,
    *,
    topic: str,
    key: str,
    payload: BaseModel | Mapping[str, Any],
    priority: int = PRIORITY_LIVE,
    clock: Clock | None = None,
) -> OutboxMessage:
    """Add one outbox row in the caller's transaction (flush, no commit, no publish).

    The relay is woken after the caller commits. Nothing publishes to the bus from business code
    except through this function and :func:`emit`.
    """
    document: dict[str, Any] = (
        payload.model_dump(mode="json")
        if isinstance(payload, BaseModel)
        else to_jsonable(dict(payload))
    )
    now = (clock or SystemClock()).now()
    row = OutboxMessage(
        topic=topic,
        msg_key=key,
        payload=document,
        priority=priority,
        not_before=now,
    )
    await uow.outbox.add(row)
    after_commit(uow, outbox_signal().notify)
    return row


async def emit(
    uow: UnitOfWork,
    event: StageEvent,
    priority: int = PRIORITY_LIVE,
    *,
    kind: TopicKind = "main",
    clock: Clock | None = None,
) -> OutboxMessage:
    """THE way to emit a ``StageEvent``. Never commits and never publishes."""
    return await enqueue(
        uow,
        topic=topic_for(event.stage, kind),
        key=str(event.work_item_id),
        payload=event,
        priority=priority,
        clock=clock,
    )
