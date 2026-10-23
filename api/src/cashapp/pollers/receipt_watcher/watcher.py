"""The Fusion receipt watcher: poller 2 of exactly 2. Its only output is outbox events.

Every cycle it asks Fusion for receipts created since the stored high-water mark, writes one
``ReceiptArrived`` outbox event per new receipt and advances the mark in the same transaction, then
escalates items that have waited past the aging limit.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from cashapp.data.repositories.awaiting import AwaitingReceiptRepository
from cashapp.data.repositories.watermark import WatermarkRace, WatermarkRepository
from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock
from cashapp.domain.receipt_arrived import RECEIPT_ARRIVED_TOPIC, ReceiptArrived
from cashapp.domain.work_item import PRIORITY_LIVE
from cashapp.integrations.fusion import FusionClient, FusionError
from cashapp.pipeline.events import default_namer, enqueue
from cashapp.pipeline.roles import RoleState, RoleStatus
from cashapp.pollers.receipt_watcher.cursor import (
    INITIAL_LOOKBACK,
    OVERLAP,
    advance_mark,
    select_new,
)
from cashapp.services.awaiting_receipt import escalate_aged
from cashapp.services.config import ConfigSnapshot, RuntimeConfig

logger = logging.getLogger(__name__)

ROLE_NAME = "receipt-watcher"
MIN_INTERVAL_SECONDS = 1
FAILURE_INTERVAL_SECONDS = 30


@dataclass(frozen=True, slots=True)
class WatcherCycleStats:
    fetched: int
    emitted: int
    aged_out: int
    fusion_error: str | None


class ReceiptWatcher:
    """Satisfies the pipeline ``Runnable`` protocol."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        fusion: FusionClient,
        config: RuntimeConfig,
        clock: Clock,
        batch_limit: int = 500,
        max_limit: int = 10_000,
        max_batches_per_cycle: int = 20,
        aging_batch: int = 100,
    ) -> None:
        self._uow_factory = uow_factory
        self._fusion = fusion
        self._config = config
        self._clock = clock
        self._batch_limit = batch_limit
        self._max_limit = max_limit
        self._max_batches = max_batches_per_cycle
        self._aging_batch = aging_batch
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

    async def run(self, stop: asyncio.Event) -> None:
        self._status = "running"
        try:
            while not stop.is_set():
                try:
                    snapshot = await self._config.snapshot()
                    interval = max(
                        MIN_INTERVAL_SECONDS, snapshot.receipt_watcher().poll_interval_seconds
                    )
                    stats = await self.run_cycle(snapshot)
                    logger.info(
                        "receipt watcher cycle done: fetched=%d emitted=%d aged_out=%d",
                        stats.fetched,
                        stats.emitted,
                        stats.aged_out,
                    )
                except Exception as exc:
                    interval = FAILURE_INTERVAL_SECONDS
                    self._status = "degraded"
                    self._detail = type(exc).__name__
                    logger.error("receipt watcher cycle failed: error=%s", type(exc).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), interval)
                except TimeoutError:
                    continue
        finally:
            self._status = "stopped"

    async def run_cycle(self, snapshot: ConfigSnapshot | None = None) -> WatcherCycleStats:
        """One pass: ingest new receipts, then age out. Tests call this directly."""
        snap = snapshot if snapshot is not None else await self._config.snapshot()
        fetched = emitted = 0
        fusion_error: str | None = None
        degraded_detail: str | None = None
        try:
            fetched, emitted, degraded_detail = await self._ingest_receipts()
        except FusionError as exc:
            fusion_error = type(exc).__name__
            logger.warning("receipt fetch from Fusion failed: error=%s", fusion_error)
        except WatermarkRace:
            logger.info("another watcher created the watermark; continuing next cycle")
        aged = await self._age_out(snap)

        self._last_activity_at = self._clock.now()
        if fusion_error is not None:
            self._status = "degraded"
            self._detail = f"Fusion receipt fetch failed: {fusion_error}"
        elif degraded_detail is not None:
            self._status = "degraded"
            self._detail = degraded_detail
        else:
            self._status = "running"
            self._detail = None
        return WatcherCycleStats(
            fetched=fetched, emitted=emitted, aged_out=aged, fusion_error=fusion_error
        )

    async def _ingest_receipts(self) -> tuple[int, int, str | None]:
        pod = self._fusion.pod_name
        topic = default_namer().named(RECEIPT_ARRIVED_TOPIC)
        limit = self._batch_limit
        total_fetched = total_emitted = 0

        for _ in range(self._max_batches):
            async with self._uow_factory() as uow:
                row = await uow.repo(WatermarkRepository).by_pod(pod)
            mark = self._clock.now() - INITIAL_LOOKBACK if row is None else row.high_water_mark

            receipts = await self._fusion.receipts_created_since(mark - OVERLAP, limit=limit)
            total_fetched += len(receipts)

            async with self._uow_factory() as uow:
                now = self._clock.now()
                watermark = await uow.repo(WatermarkRepository).lock_or_create(
                    pod, initial_mark=mark, now=now
                )
                fresh = select_new(receipts, watermark.high_water_mark, watermark.seen_at_mark)
                for receipt in fresh:
                    await enqueue(
                        uow,
                        topic=topic,
                        key=str(receipt.receipt_id),
                        payload=ReceiptArrived.from_fusion(receipt),
                        priority=PRIORITY_LIVE,
                        clock=self._clock,
                    )
                new_mark, new_seen = advance_mark(
                    watermark.high_water_mark, watermark.seen_at_mark, fresh
                )
                watermark.high_water_mark = new_mark
                watermark.seen_at_mark = new_seen
                watermark.updated_at = now
                await uow.session.flush()
                await uow.commit()
            total_emitted += len(fresh)

            if len(receipts) < limit:
                return total_fetched, total_emitted, None
            if fresh:
                continue
            # A full batch with nothing new: more receipts share the overlap window than asked for.
            if limit >= self._max_limit:
                logger.warning("receipt batch limit reached without progress: limit=%d", limit)
                return total_fetched, total_emitted, "receipt batch limit reached without progress"
            limit = min(limit * 2, self._max_limit)
        return total_fetched, total_emitted, None

    async def _age_out(self, snap: ConfigSnapshot) -> int:
        max_days = snap.aging().awaiting_receipt_max_days
        total = 0
        for _ in range(self._max_batches):
            async with self._uow_factory() as uow:
                now = self._clock.now()
                items = await uow.repo(AwaitingReceiptRepository).aged_out(
                    cutoff=now - timedelta(days=max_days), now=now, limit=self._aging_batch
                )
                if not items:
                    return total
                escalated = await escalate_aged(uow, items, max_days=max_days, clock=self._clock)
                await uow.commit()
            total += len(escalated)
            if len(items) < self._aging_batch:
                break
        return total
