"""FastAPI application factory."""

from fastapi import FastAPI

from cashapp import __version__
from cashapp.api.discovery import discover_routers
from cashapp.api.errors import ERROR_RESPONSES, install_error_handlers
from cashapp.api.middleware import RequestIdMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="Fusion CashApp API", version=__version__, responses=ERROR_RESPONSES)
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    for router in discover_routers("cashapp.api.routers"):
        app.include_router(router)
    return app


app = create_app()
