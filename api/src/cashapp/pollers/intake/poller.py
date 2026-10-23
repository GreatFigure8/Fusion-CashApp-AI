"""The intake poller: poller 1 of exactly 2. Its only output is new work items and their events."""

import asyncio
import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from cashapp.integrations.storage.base import ObjectStore
from cashapp.pipeline.roles import Container, RoleState, RoleStatus
from cashapp.pollers.intake.hooks import CYCLE_HOOKS, CycleHook, run_cycle_hooks
from cashapp.pollers.intake.ingest import Normaliser, ingest
from cashapp.pollers.intake.sources import ArtifactSource
from cashapp.services.normalise import normalise

logger = logging.getLogger(__name__)

ROLE_NAME = "intake-poller"
MIN_INTERVAL_SECONDS = 1


@dataclass(frozen=True, slots=True)
class CycleStats:
    ingested: int
    duplicates: int
    failed: int
    source_errors: int


class IntakePoller:
    """Satisfies the pipeline ``Runnable`` protocol."""

    def __init__(
        self,
        *,
        container: Container,
        sources: Sequence[ArtifactSource],
        object_store: ObjectStore,
        hooks: Sequence[CycleHook] | None = None,
        normaliser: Normaliser = normalise,
    ) -> None:
        self._container = container
        self._sources = list(sources)
        self._object_store = object_store
        self._hooks = hooks  # None means the live CYCLE_HOOKS list
        self._normaliser = normaliser
        self._stop: asyncio.Event | None = None
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
        self._stop = stop
        self._status = "running"
        try:
            while not stop.is_set():
                try:
                    cfg = await self._container.config.snapshot()
                    interval = max(MIN_INTERVAL_SECONDS, cfg.intake().poll_interval_seconds)
                    await self.run_cycle()
                except Exception as exc:
                    interval = 30
                    self._status = "degraded"
                    self._detail = f"cycle failed: {type(exc).__name__}"
                    logger.error("intake cycle failed: error=%s", type(exc).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), interval)
                except TimeoutError:
                    continue
        finally:
            self._status = "stopped"

    async def run_cycle(self) -> CycleStats:
        """One pass over every source, then the cycle hooks. Tests call this directly."""
        ingested = duplicates = failed = source_errors = 0
        for source in self._sources:
            kind = type(source).__name__
            try:
                async for artifact in source.fetch_new():
                    if self._stopping():
                        break
                    try:
                        result = await ingest(
                            self._container.uow_factory,
                            self._object_store,
                            artifact,
                            source_kind=artifact.source_kind,
                            clock=self._container.clock,
                            normaliser=self._normaliser,
                        )
                        await source.mark_processed(artifact.source_ref, "processed")
                    except Exception as exc:
                        failed += 1
                        logger.error(
                            "intake of an artifact failed: error=%s source=%s hash=%s",
                            type(exc).__name__,
                            artifact.source_kind.value,
                            hashlib.sha256(artifact.data).hexdigest(),
                        )
                        await self._mark_failed(source, artifact.source_ref)
                        continue
                    if result.duplicate_of is not None:
                        duplicates += 1
                    else:
                        ingested += 1
            except Exception as exc:
                source_errors += 1
                logger.error(
                    "fetching from an intake source failed: source=%s error=%s",
                    kind,
                    type(exc).__name__,
                )

        now = self._container.clock.now()
        hooks = CYCLE_HOOKS if self._hooks is None else self._hooks
        await run_cycle_hooks(hooks, self._container, now)

        stats = CycleStats(ingested, duplicates, failed, source_errors)
        self._last_activity_at = self._container.clock.now()
        if source_errors:
            self._status = "degraded"
            self._detail = f"{source_errors} source(s) failed to fetch"
        else:
            self._status = "running"
            self._detail = None
        logger.info(
            "intake cycle done: ingested=%d duplicates=%d failed=%d source_errors=%d",
            ingested,
            duplicates,
            failed,
            source_errors,
        )
        return stats

    def _stopping(self) -> bool:
        return self._stop is not None and self._stop.is_set()

    @staticmethod
    async def _mark_failed(source: ArtifactSource, ref: str) -> None:
        try:
            await source.mark_processed(ref, "failed")
        except Exception as exc:
            logger.error("marking an artifact failed did not work: error=%s", type(exc).__name__)
