"""Where a backlog import reads from: a validated folder, or a mailbox folder through an adapter.

The API accepts only a folder name relative to ``<intake.drop_folder>/backlog/``. Name validation
and resolved-path containment are two independent checks, and both run before any file is touched.
Absolute paths are for the CLI only (trusted operator input, see ``tools/backlog``).
"""

import importlib
import re
from pathlib import Path
from typing import Final, cast

from cashapp.pollers.intake.sources import MailboxSource
from cashapp.services.backlog.service import BacklogSourceError
from cashapp.settings import Settings

BACKLOG_SUBDIR: Final = "backlog"
_SEGMENT: Final = re.compile(r"^[A-Za-z0-9._-]+$")
_MAILBOX_FACTORY_MODULE: Final = "cashapp.integrations.mail.factory"
_MAILBOX_FACTORY_NAME: Final = "build_mailbox_source"


def resolve_backlog_folder(settings: Settings, folder: str) -> Path:
    """The existing directory ``folder`` names under the backlog root, or ``BacklogSourceError``."""
    # Check 1: the name. Relative, plain segments, no traversal.
    if not folder or folder.startswith(("/", "\\")) or Path(folder).is_absolute():
        raise BacklogSourceError("folder must be a relative name")
    segments = folder.split("/")
    for segment in segments:
        if segment in {"", ".", ".."} or _SEGMENT.fullmatch(segment) is None:
            raise BacklogSourceError("folder contains an invalid path segment")
    # Check 2: the resolved path, which follows symlinks, must stay inside the backlog root.
    root = (Path(settings.intake.drop_folder) / BACKLOG_SUBDIR).resolve()
    candidate = (root / Path(*segments)).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise BacklogSourceError("folder resolves outside the backlog root")
    if not candidate.is_dir():
        raise BacklogSourceError("folder does not exist")
    return candidate


def resolve_stored_folder(settings: Settings, source_ref: str) -> Path:
    """Re-validate the folder an API-created batch stored, before a resumed import reads it."""
    root = (Path(settings.intake.drop_folder) / BACKLOG_SUBDIR).resolve()
    try:
        relative = Path(source_ref).resolve().relative_to(root)
    except ValueError as exc:
        raise BacklogSourceError("folder resolves outside the backlog root") from exc
    return resolve_backlog_folder(settings, relative.as_posix())


def build_backlog_mailbox_source(settings: Settings, folder: str) -> MailboxSource:
    """The real mailbox adapter reading ``folder``; absent until the mailbox follow-up is built."""
    if not folder.strip():
        raise BacklogSourceError("mailbox folder name is required")
    try:
        module = importlib.import_module(_MAILBOX_FACTORY_MODULE)
        factory = getattr(module, _MAILBOX_FACTORY_NAME)
    except (ImportError, AttributeError) as exc:
        raise BacklogSourceError("mailbox adapter not available") from exc
    return cast(MailboxSource, factory(settings, folder=folder))
