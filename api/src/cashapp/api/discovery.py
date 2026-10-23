"""Router auto-discovery: new endpoints are new modules, never edits to main.py."""

import importlib
import pkgutil

from fastapi import APIRouter


def discover_routers(package: str) -> list[APIRouter]:
    """Import every non-underscore module directly in `package`; return their `router`s.

    Import errors propagate so a broken router fails fast at startup.
    """
    pkg = importlib.import_module(package)
    routers: list[APIRouter] = []
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package}.{info.name}")
        candidate = getattr(module, "router", None)
        if isinstance(candidate, APIRouter):
            routers.append(candidate)
    return routers
