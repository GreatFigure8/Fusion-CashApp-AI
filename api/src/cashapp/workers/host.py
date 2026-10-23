"""The worker host: runs the selected roles as long-running async tasks in one process.

Start-up recovers expired claims once, then starts the health server, telemetry and the roles.
A stop signal lets in-flight items finish within the grace period; whatever is still in flight
afterwards has its claim released in its own transaction. A role that ends while the host is not
stopping is a crash: the host stops everything and returns exit code 1 so the platform restarts it.
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Sequence
from types import FrameType
from typing import cast

from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.pipeline.roles import Container, RoleSpec, RoleState, Runnable
from cashapp.services.claims import ClaimService
from cashapp.workers.container import WorkerContainer
from cashapp.workers.health import HealthServer, build_health_app
from cashapp.workers.telemetry import HostTelemetry

log = logging.getLogger(__name__)

CANCEL_WAIT_SECONDS = 5.0
RELEASE_REASON = "shutdown grace exceeded"


class WorkerHost:
    def __init__(
        self,
        container: WorkerContainer,
        roles: Sequence[RoleSpec],
        *,
        health_port: int | None,
        install_signals: bool = True,
    ) -> None:
        self._container = container
        self._roles = list(roles)
        self._health_port = (
            health_port if health_port is not None else container.settings.worker.health_port
        )
        self._install_signals = install_signals
        self._stop = asyncio.Event()
        self._force = asyncio.Event()
        self._runnables: dict[str, Runnable] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stopping = False
        self.alive = False

    # --- state ----------------------------------------------------------------------------

    def role_states(self) -> list[RoleState]:
        states: list[RoleState] = []
        for spec in self._roles:
            runnable = self._runnables.get(spec.name)
            task = self._tasks.get(spec.name)
            if runnable is None:
                states.append(RoleState(spec.name, "stopping" if self._stopping else "starting"))
            elif task is not None and task.done():
                states.append(RoleState(spec.name, "stopped", detail=self._task_detail(task)))
            else:
                state = runnable.state()
                if self._stopping and state.status != "stopped":
                    state = RoleState(state.name, "stopping", state.last_activity_at, state.detail)
                states.append(state)
        return states

    @staticmethod
    def _task_detail(task: asyncio.Task[None]) -> str | None:
        if task.cancelled():
            return "cancelled"
        exc = task.exception()
        return type(exc).__name__ if exc is not None else None

    def request_stop(self) -> None:
        """What the signal handlers call. A second request skips the rest of the grace period."""
        if self._stop.is_set():
            self._force.set()
        self._stop.set()

    # --- signals --------------------------------------------------------------------------

    def _hook_signals(self, loop: asyncio.AbstractEventLoop) -> dict[int, object]:
        """Install SIGTERM/SIGINT handlers; return handlers to restore (fallback path only)."""
        previous: dict[int, object] = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.request_stop)
            except (NotImplementedError, RuntimeError):
                previous[sig] = signal.getsignal(sig)

                def handler(_signum: int, _frame: FrameType | None) -> None:
                    loop.call_soon_threadsafe(self.request_stop)

                signal.signal(sig, handler)
        return previous

    def _unhook_signals(self, loop: asyncio.AbstractEventLoop, previous: dict[int, object]) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            if sig in previous:
                original = previous[sig]
                if original is not None:
                    signal.signal(sig, original)  # pyright: ignore[reportArgumentType]
            else:
                with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                    loop.remove_signal_handler(sig)

    # --- run ------------------------------------------------------------------------------

    async def run(self) -> int:
        loop = asyncio.get_running_loop()
        previous = self._hook_signals(loop) if self._install_signals else {}
        container = self._container
        health: HealthServer | None = None
        telemetry = HostTelemetry(container)
        telemetry_stop = asyncio.Event()
        telemetry_task: asyncio.Task[None] | None = None
        exit_code = 0
        try:
            recovered = await ClaimService(container.uow_factory, container.clock).recover_expired()
            log.info("startup recovery done", extra={"recovered": recovered})
            await self._verify_fusion_framework()

            container.set_on_processed(telemetry.notify_processed)
            telemetry_task = asyncio.create_task(telemetry.run(telemetry_stop), name="telemetry")
            if self._health_port != 0:
                health = HealthServer(build_health_app(self), self._health_port)
                await health.start()
            self.alive = True

            exit_code = await self._run_roles()
        finally:
            self.alive = False
            await self._release_inflight()
            telemetry_stop.set()
            if telemetry_task is not None:
                await self._await_quietly(telemetry_task)
            if health is not None:
                await health.stop()
            await container.aclose()
            self._unhook_signals(loop, previous)
        return exit_code

    async def _verify_fusion_framework(self) -> None:
        """Fail start if the Fusion REST probe 400s (a wrong REST-Framework-Version); an
        unreachable or unconfigured MCP server is logged and start continues."""
        try:
            fusion = self._container.resolve(FusionClient)
            verify = getattr(fusion, "verify_framework", None)
            if verify is not None:
                await verify()
        except FusionError as exc:
            if exc.http_status == 400:
                raise
            log.warning("fusion check skipped", extra={"fusion_code": exc.code.value})
        except Exception as exc:
            log.warning("fusion check skipped", extra={"error_type": type(exc).__name__})

    async def _run_roles(self) -> int:
        stop = self._stop
        exit_code = 0
        try:
            for spec in self._roles:
                runnable = spec.build(cast(Container, self._container))
                self._runnables[spec.name] = runnable
                self._tasks[spec.name] = asyncio.create_task(
                    runnable.run(stop), name=f"role:{spec.name}"
                )
            log.info("roles started", extra={"roles": [spec.name for spec in self._roles]})

            stop_waiter = asyncio.ensure_future(stop.wait())
            try:
                await asyncio.wait(
                    {stop_waiter, *self._tasks.values()}, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                stop_waiter.cancel()
            if not stop.is_set():
                exit_code = 1
                for name, task in self._tasks.items():
                    if task.done():
                        log.error(
                            "role ended unexpectedly",
                            extra={"role": name, "error_type": self._task_detail(task)},
                        )
        except Exception:
            log.exception("role start-up failed")
            exit_code = 1

        self._stopping = True
        stop.set()
        await self._wait_for_grace()
        await self._cancel_remaining()
        return exit_code

    async def _wait_for_grace(self) -> None:
        loop = asyncio.get_running_loop()
        grace = await self._container.runtime.shutdown_grace_seconds()
        deadline = loop.time() + grace
        pending: set[asyncio.Task[None]] = {t for t in self._tasks.values() if not t.done()}
        while pending:
            remaining = deadline - loop.time()
            if remaining <= 0 or self._force.is_set():
                break
            force_waiter = asyncio.ensure_future(self._force.wait())
            try:
                await asyncio.wait(
                    {force_waiter, *pending},
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                force_waiter.cancel()
            pending = {task for task in pending if not task.done()}

    async def _cancel_remaining(self) -> None:
        remaining = [task for task in self._tasks.values() if not task.done()]
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.wait(remaining, timeout=CANCEL_WAIT_SECONDS)
        for name, task in self._tasks.items():
            if task.done() and not task.cancelled() and task.exception() is not None:
                log.error(
                    "role failed during shutdown",
                    extra={"role": name, "error_type": self._task_detail(task)},
                )

    async def _release_inflight(self) -> None:
        """Return every still-claimed item to PENDING; a committed outcome is never overwritten."""
        inflight = self._container.bus.inflight()
        if not inflight:
            return
        claims = ClaimService(self._container.uow_factory, self._container.clock)
        for entry in inflight:
            try:
                released = await claims.release(
                    entry.work_item_id, entry.stage, reason=RELEASE_REASON
                )
            except Exception:
                log.exception("claim release failed", extra={"work_item_id": entry.work_item_id})
                continue
            if released:
                log.warning(
                    "claim released at shutdown",
                    extra={"work_item_id": entry.work_item_id, "stage": entry.stage.value},
                )

    @staticmethod
    async def _await_quietly(task: asyncio.Task[None]) -> None:
        try:
            await asyncio.wait_for(task, timeout=CANCEL_WAIT_SECONDS)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
        except Exception:
            log.exception("telemetry ended with an error")
