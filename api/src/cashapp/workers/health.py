"""The worker's health server: /livez (loop alive) and /readyz (every role running)."""

import asyncio
import contextlib
from collections.abc import Generator
from typing import Any, Protocol

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from cashapp.pipeline.roles import RoleState


class HealthSource(Protocol):
    @property
    def alive(self) -> bool: ...

    def role_states(self) -> list[RoleState]: ...


def _role_json(state: RoleState) -> dict[str, Any]:
    return {
        "name": state.name,
        "status": state.status,
        "last_activity_at": (
            state.last_activity_at.isoformat() if state.last_activity_at is not None else None
        ),
        "detail": state.detail,
    }


def build_health_app(source: HealthSource) -> Starlette:
    async def livez(_: Request) -> Response:
        if source.alive:
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "down"}, status_code=503)

    async def readyz(_: Request) -> Response:
        states = source.role_states()
        roles = [_role_json(state) for state in states]
        ready = source.alive and all(state.status == "running" for state in states)
        if ready:
            return JSONResponse({"status": "ready", "roles": roles})
        return JSONResponse({"status": "not_ready", "roles": roles}, status_code=503)

    return Starlette(routes=[Route("/livez", livez), Route("/readyz", readyz)])


class _Server(uvicorn.Server):
    """A uvicorn server that leaves signal handling to the worker host."""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None]:
        yield

    def install_signal_handlers(self) -> None:
        return None


class HealthServer:
    def __init__(self, app: Starlette, port: int) -> None:
        config = uvicorn.Config(
            app,
            host="0.0.0.0",  # noqa: S104 - the platform probe reaches the container address
            port=port,
            log_config=None,
            access_log=False,
        )
        self._server = _Server(config)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            if self._task.done():
                await self._task  # surfaces a bind failure
                return
            await asyncio.sleep(0.01)

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            await self._task
            self._task = None
