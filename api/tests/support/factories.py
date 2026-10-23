"""Model factories for tests. They build unsaved rows."""

import hashlib
import uuid
from typing import Any

from cashapp.data.models.work_item import WorkItem
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.work_item import PRIORITY_LIVE, SourceKind


def make_work_item(**overrides: Any) -> WorkItem:
    """An unsaved WorkItem at CLASSIFY/PENDING with a unique content hash."""
    fields: dict[str, Any] = {
        "source_kind": SourceKind.FOLDER,
        "content_hash": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        "stage": Stage.CLASSIFY,
        "state": ItemState.PENDING,
        "priority": PRIORITY_LIVE,
        "info_flags": [],
        "attempts": 0,
    }
    fields.update(overrides)
    return WorkItem(**fields)
