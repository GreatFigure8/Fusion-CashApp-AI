"""Consumes ``ReceiptArrived`` events and wakes the items waiting for that receipt.

A plain Runnable, not a ``StageRunner``: the event carries a receipt, so there is no work item to
claim. The offset is committed only after the database commit, and a redelivery is a no-op because
the woken items are no longer AWAITING_RECEIPT.
"""

import asyncio
import contextlib
import logging
from datetime import datetime

from pydantic import ValidationError

from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock
from cashapp.domain.engine import ConsumerRef
from cashapp.domain.receipt_arrived import RECEIPT_ARRIVED_TOPIC, ReceiptArrived
from cashapp.pipeline.bus import Delivery, EventBus, close_stream, next_or_stop
from cashapp.pipeline.events import TopicNamer, enqueue
from cashapp.pipeline.roles import RoleState, RoleStatus
from cashapp.services.awaiting_receipt import WakeResult, wake_for_receipt
from cashapp.services.config import RuntimeConfig
from cashapp.services.engine.pause_gate import PauseGate

logger = logging.getLogger(__name__)

ROLE_NAME = "receipt-arrived"
MAX_BACKOFF_SECONDS = 30
RAW_LIMIT = 4000


class ReceiptArrivedConsumer:
    """Satisfies the pipeline ``Runnable`` protocol."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        bus: EventBus,
        group: str,
        config: RuntimeConfig,
        clock: Clock,
        namer: TopicNamer,
        pause_gate: PauseGate | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._bus = bus
        self._group = group
        self._config = config
        self._clock = clock
        self._namer = namer
        self._pause_gate = pause_gate
        self._status: RoleStatus = "starting"
        self._detail: str | None = None
        self._last_activity_at: datetime | None = None

    def state(self) -> RoleState:
        return RoleState(
            name=ROLE_NAME,
            status=self._status,
            last_activity_at=self._last_activity_at,
            detail=self._detail,
        )

    async def handle(self, delivery: Delivery) -> WakeResult | None:
        """Process one delivery and commit its offset. ``None`` means the event was malformed."""
        try:
            event = ReceiptArrived.model_validate_json(delivery.value)
        except ValidationError:
            await self._dead_letter(delivery)
            await delivery.commit()
            return None

        snapshot = await self._config.snapshot()
        async with self._uow_factory() as uow:
            result = await wake_for_receipt(
                uow, event, matching=snapshot.matching(), clock=self._clock
            )
            await uow.commit()
        await delivery.commit()
        logger.info(
            "receipt event handled: receipt_id=%d woken=%d", event.receipt_id, len(result.woken_ids)
        )
        return result

    async def _dead_letter(self, delivery: Delivery) -> None:
        raw = delivery.value.decode("utf-8", errors="replace")[:RAW_LIMIT]
        async with self._uow_factory() as uow:
            await enqueue(
                uow,
                topic=self._namer.named(f"{RECEIPT_ARRIVED_TOPIC}.dlq"),
                key=delivery.key or "malformed",
                payload={
                    "error": "malformed",
                    "source_topic": delivery.topic,
                    "partition": delivery.partition,
                    "offset": delivery.offset,
                    "raw": raw,
                },
                clock=self._clock,
            )
            await uow.commit()
        logger.warning(
            "malformed receipt event sent to dead letter: partition=%d offset=%d",
            delivery.partition,
            delivery.offset,
        )

    async def _handle_with_retry(self, delivery: Delivery, stop: asyncio.Event) -> bool:
        """Retry the same delivery while the infrastructure is down; False when stopped first."""
        backoff = 1
        while True:
            try:
                await self.handle(delivery)
            except Exception as exc:
                self._status = "degraded"
                self._detail = type(exc).__name__
                logger.warning("receipt delivery failed; will retry: error=%s", type(exc).__name__)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                if stop.is_set():
                    return False  # not committed: redelivered after the restart
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            else:
                self._status = "running"
                self._detail = None
                self._last_activity_at = self._clock.now()
                return True

    async def run(self, stop: asyncio.Event) -> None:
        topic = self._namer.named(RECEIPT_ARRIVED_TOPIC)
        stream = self._bus.subscribe([topic], self._group)
        self._status = "running"
        try:
            while not stop.is_set():
                if self._pause_gate is not None:
                    # Paused: receipt events stay uncommitted on the bus until resumed.
                    await self._pause_gate.wait_while_paused(ConsumerRef.receipt_arrived(), stop)
                    if stop.is_set():
                        break
                delivery = await next_or_stop(stream, stop)
                if delivery is None:
                    break
                if not await self._handle_with_retry(delivery, stop):
                    break
        finally:
            self._status = "stopping"
            await close_stream(stream)
            self._status = "stopped"
