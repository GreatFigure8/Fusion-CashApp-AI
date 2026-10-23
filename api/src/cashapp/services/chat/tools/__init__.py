"""Tool discovery: every module here that exports ``TOOLS`` is registered at startup.

Mirrors router discovery: a new tool is a new module, never an edit to a central list. This
package's ``__init__`` imports its submodules only inside functions, so a tool module can import
``registry`` without a cycle.
"""

import importlib
import pkgutil
from typing import Any, cast

from cashapp.services.chat.tools.registry import ToolRegistry, ToolSpec

DEFAULT_PACKAGE = "cashapp.services.chat.tools"


def discover_tools(package: str = DEFAULT_PACKAGE) -> list[ToolSpec[Any, Any]]:
    """Import every non-underscore module directly in ``package``; collect their ``TOOLS``.

    A module without ``TOOLS`` is skipped. Import errors propagate so a broken tool fails fast.
    """
    pkg = importlib.import_module(package)
    specs: list[ToolSpec[Any, Any]] = []
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package}.{info.name}")
        found = getattr(module, "TOOLS", None)
        if isinstance(found, list):
            for spec in cast("list[Any]", found):
                if isinstance(spec, ToolSpec):
                    specs.append(cast("ToolSpec[Any, Any]", spec))
    return specs


def build_registry(package: str = DEFAULT_PACKAGE) -> ToolRegistry:
    registry = ToolRegistry()
    for spec in discover_tools(package):
        registry.register(spec)
    return registry


__all__ = ["DEFAULT_PACKAGE", "build_registry", "discover_tools"]
