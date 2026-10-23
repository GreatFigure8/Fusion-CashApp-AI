"""Cycle hooks: work other stories run after each intake cycle (reports, retention purge)."""

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from cashapp.pipeline.roles import Container

logger = logging.getLogger(__name__)


class CycleHook(Protocol):
    async def on_cycle(self, container: Container, now: datetime) -> None: ...


# s41 and s45 append to this list from their own packages; nothing here imports them.
CYCLE_HOOKS: list[CycleHook] = []


async def run_cycle_hooks(hooks: Sequence[CycleHook], container: Container, now: datetime) -> None:
    """Await each hook in order; a failing hook is logged and never stops the others or the loop."""
    for hook in list(hooks):
        try:
            await hook.on_cycle(container, now)
        except Exception as exc:
            logger.error(
                "intake cycle hook failed: hook=%s error=%s",
                type(hook).__name__,
                type(exc).__name__,
            )


# s45: the retention purge runs from the intake cycle, at most once an hour.
from cashapp.services.retention.hook import RetentionCycleHook  # noqa: E402

if not any(isinstance(hook, RetentionCycleHook) for hook in CYCLE_HOOKS):
    CYCLE_HOOKS.append(RetentionCycleHook())


# s35: batch completion and the cancel sweep for backlog reprocessing.
from cashapp.services.backlog.hook import BacklogCycleHook  # noqa: E402

if not any(isinstance(hook, BacklogCycleHook) for hook in CYCLE_HOOKS):
    CYCLE_HOOKS.append(BacklogCycleHook())

# s19: the flow monitor shows when the intake poller last completed a cycle.
from cashapp.services.poller_heartbeat import PollerHeartbeatHook  # noqa: E402

if not any(isinstance(hook, PollerHeartbeatHook) for hook in CYCLE_HOOKS):
    CYCLE_HOOKS.append(PollerHeartbeatHook("intake-poller"))
