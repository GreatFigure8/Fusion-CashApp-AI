"""Tool-service provider discovery: a new provider is a new module here, never a central edit.

A provider module exports ``PROVIDERS: dict[type, Provider]`` mapping a service type to a
zero-argument callable (sync or async) that builds it from the same dependency the routers use.
This layer exists so the business layer never imports the API layer: tools ask
``ToolContext.services`` for a type and never know where it came from.
"""

import importlib
import pkgutil
from collections.abc import Mapping
from typing import Any

from cashapp.services.chat.tools.registry import Provider

DEFAULT_PACKAGE = "cashapp.api.tool_providers"


def discover_providers(package: str = DEFAULT_PACKAGE) -> dict[type[Any], Provider]:
    """Import every non-underscore module in ``package`` and merge their ``PROVIDERS``.

    A service type provided twice is refused; import errors propagate.
    """
    pkg = importlib.import_module(package)
    merged: dict[type[Any], Provider] = {}
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package}.{info.name}")
        found = getattr(module, "PROVIDERS", None)
        if not isinstance(found, Mapping):
            continue
        for kind, provider in found.items():  # pyright: ignore[reportUnknownVariableType]
            if kind in merged:
                raise RuntimeError(f"service {kind!r} is provided by more than one module")  # pyright: ignore[reportUnknownVariableType]
            merged[kind] = provider  # pyright: ignore[reportUnknownVariableType]
    return merged


__all__ = ["DEFAULT_PACKAGE", "discover_providers"]
