"""In-process plumbing for background replays: task references and a progress hub.

A replay is an ordinary ``asyncio`` task started by the request that asked for it. It is not a
scheduler and not a poller (non-negotiables 4 and 5). Tasks are held in a set until they finish
so they are never garbage collected mid-run.
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncGenerator, Awaitable
from dataclasses import dataclass, field
from typing import Any, Final, Literal

BOOT_ID: Final = str(uuid.uuid4())
"""Identifies this API process; a RUNNING replay from another boot has lost its runner."""

HEARTBEAT_STALE_SECONDS: Final = 180  # progress is persisted per batch, a batch can take a while
_QUEUE_SIZE: Final = 256

ProgressKind = Literal["progress", "done", "failed"]


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    kind: ProgressKind
    data: dict[str, Any]

    @property
    def terminal(self) -> bool:
        return self.kind != "progress"


@dataclass(slots=True)
class ReplayProgressHub:
    """Fan-out of progress events to the SSE streams that are open for a replay."""

    _queues: dict[int, list[asyncio.Queue[ProgressEvent]]] = field(
        default_factory=lambda: dict[int, list[asyncio.Queue[ProgressEvent]]]()
    )

    def publish(self, replay_id: int, event: ProgressEvent) -> None:
        for queue in self._queues.get(replay_id, []):
            if queue.full():
                # Progress is a running total, so dropping the oldest frame loses nothing.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(event)

    async def subscribe(self, replay_id: int) -> AsyncGenerator[ProgressEvent, None]:
        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._queues.setdefault(replay_id, []).append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.terminal:
                    return
        finally:
            subscribers = self._queues.get(replay_id, [])
            if queue in subscribers:
                subscribers.remove(queue)
            if not subscribers:
                self._queues.pop(replay_id, None)

    def has_subscribers(self, replay_id: int) -> bool:
        return bool(self._queues.get(replay_id))


class LabTaskRegistry:
    """Process-wide holder of replay tasks and the progress hub."""

    def __init__(self) -> None:
        self.hub = ReplayProgressHub()
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def start(self, replay_id: int, work: Awaitable[None]) -> None:
        """Run ``work`` in the background and keep a reference until it is done."""

        async def runner() -> None:
            await work

        task = asyncio.create_task(runner(), name=f"lab-replay-{replay_id}")
        self._tasks[replay_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(replay_id, None))

    def is_running(self, replay_id: int) -> bool:
        return replay_id in self._tasks
