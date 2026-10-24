"""FastAPI application factory."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from cashapp import __version__
from cashapp.api.deps import get_uow_factory
from cashapp.api.discovery import discover_routers
from cashapp.api.errors import ERROR_RESPONSES, install_error_handlers
from cashapp.api.middleware import RequestIdMiddleware
from cashapp.api.runtime_deps import set_runtime_settings
from cashapp.observability import configure_observability_bootstrap, reconfigure_observability
from cashapp.services.runtime_settings import build_runtime_settings
from cashapp.settings import Settings, get_settings

logger = logging.getLogger(__name__)

SERVICE_NAME = "cashapp-api"


def _lifespan(settings: Settings | None):
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        # Uvicorn serves nothing until this finishes, so no request can arrive (or be
        # authenticated) before the DB-stored settings, identity included, are loaded.
        resolved = settings if settings is not None else get_settings()
        runtime = build_runtime_settings(resolved, get_uow_factory())
        # Not strict: a fresh database has no settings yet, and the API must be up for them to be
        # entered. Workers still refuse to start with a required key unset.
        await runtime.start(strict=False)
        reconfigure_observability(runtime, service_name=SERVICE_NAME)
        set_runtime_settings(runtime)
        logger.info("api settings loaded")
        try:
            yield
        finally:
            set_runtime_settings(None)

    return lifespan


def create_app(*, settings: Settings | None = None) -> FastAPI:
    # Logging starts at INFO on stderr so the settings loader's own warnings are not lost.
    configure_observability_bootstrap(service_name=SERVICE_NAME)
    # A bad bootstrap configuration fails here, before the app is built.
    if settings is None:
        get_settings()
    app = FastAPI(
        title="Fusion CashApp API",
        version=__version__,
        responses=ERROR_RESPONSES,
        lifespan=_lifespan(settings),
    )
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    for router in discover_routers("cashapp.api.routers"):
        app.include_router(router)
    return app


def __getattr__(name: str) -> Any:
    """`cashapp.main:app` is built on first access, so importing this module needs no env."""
    if name == "app":
        built = create_app()
        globals()["app"] = built
        return built
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
