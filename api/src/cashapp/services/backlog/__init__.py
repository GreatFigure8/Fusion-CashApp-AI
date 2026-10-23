"""Backlog reprocessing.

The public names (see ``_EXPORTS``) are re-exported lazily (PEP 562): the intake poller imports
this package's hook while it is itself still being imported, so eager re-exports would be a cycle.
"""

import importlib
from typing import Any, Final

_EXPORTS: Final[dict[str, str]] = {
    "DRY_RUN_KEY_PREFIX": "dry_run",
    "is_dry_run": "dry_run",
    "record_dry_run_line": "dry_run",
    "settle_dry_run_reservation": "dry_run",
    "BacklogCycleHook": "hook",
    "BacklogError": "service",
    "BacklogNameTaken": "service",
    "BacklogNotFound": "service",
    "BacklogResumeViaCli": "service",
    "BacklogService": "service",
    "BacklogSourceError": "service",
    "BacklogTransitionError": "service",
    "backlog_error_to_api": "service",
    "BACKLOG_SUBDIR": "sources",
    "build_backlog_mailbox_source": "sources",
    "resolve_backlog_folder": "sources",
    "BacklogThrottle": "throttle",
    "TokenBucket": "throttle",
    "build_backlog_throttle": "throttle",
}


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f"{__name__}.{module}"), name)
