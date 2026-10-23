"""ORM models, one module per domain area. A new module here is discovered automatically."""

import importlib
import pkgutil

from cashapp.data.models.base import Base

__all__ = ["Base", "load_all_models"]


def load_all_models() -> None:
    """Import every submodule so all tables are registered on ``Base.metadata``.

    Later stories add a module under this package and never edit this file.
    """
    for info in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{info.name}")
