"""FastAPI application factory."""

from typing import Any

from fastapi import FastAPI

from cashapp import __version__
from cashapp.api.discovery import discover_routers
from cashapp.api.errors import ERROR_RESPONSES, install_error_handlers
from cashapp.api.middleware import RequestIdMiddleware
from cashapp.settings import Settings, get_settings


def create_app(*, settings: Settings | None = None) -> FastAPI:
    # A bad configuration fails here, before the app is built.
    if settings is None:
        get_settings()
    app = FastAPI(title="Fusion CashApp API", version=__version__, responses=ERROR_RESPONSES)
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
