"""Fusion CashApp AI: automated cash application for Oracle Fusion Receivables."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cashapp")
except PackageNotFoundError:  # pragma: no cover - only when run from an uninstalled tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
