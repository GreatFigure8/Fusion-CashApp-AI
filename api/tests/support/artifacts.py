"""Helpers over the synthetic artifact fixtures in ``tests/fixtures/artifacts``."""

import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cashapp.domain.artifacts import IncomingArtifact
from cashapp.domain.work_item import SourceKind

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "artifacts"
_CONTENT_TYPES = {".eml": "message/rfc822", ".msg": "application/vnd.ms-outlook"}


def fixture_path(name: str) -> Path:
    path = FIXTURE_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"no artifact fixture named {name!r}")
    return path


def fixture_bytes(name: str) -> bytes:
    return fixture_path(name).read_bytes()


def make_incoming(name: str, **overrides: Any) -> IncomingArtifact:
    """An ``IncomingArtifact`` over fixture ``name``; any field can be overridden by keyword."""
    suffix = Path(name).suffix.lower()
    guessed, _ = mimetypes.guess_type(name)
    fields: dict[str, Any] = {
        "source_kind": SourceKind.FOLDER,
        "source_ref": name,
        "filename": name,
        "content_type": _CONTENT_TYPES.get(suffix) or guessed or "application/octet-stream",
        "data": fixture_bytes(name),
        "received_at": datetime(2026, 1, 15, 9, 30, tzinfo=UTC),
        "sender": None,
        "subject": None,
    }
    fields.update(overrides)
    return IncomingArtifact(**fields)
