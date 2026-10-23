"""Artifact vocabulary shared by intake (s06) and normalisation (s34).

Pure frozen dataclasses and enums. No I/O, no ORM, no integrations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from cashapp.domain.work_item import SourceKind


@dataclass(frozen=True, slots=True)
class IncomingArtifact:
    """One untouched artifact as it arrived from the mailbox or a folder."""

    source_kind: SourceKind
    source_ref: str  # folder path / mailbox message id; opaque to normalise
    filename: str  # "message.eml" for mail; original file name for folders
    content_type: str | None  # declared MIME type; sniffing wins over it
    data: bytes  # the untouched original
    received_at: datetime  # tz-aware UTC
    sender: str | None = None
    subject: str | None = None


class PartKind(StrEnum):
    """Values match the ARTIFACT_PART.KIND column exactly."""

    TEXT = "TEXT"
    PDF = "PDF"
    IMAGE = "IMAGE"
    TABLE = "TABLE"
    DOCX = "DOCX"


@dataclass(frozen=True, slots=True)
class NormalisedPart:
    kind: PartKind
    media_type: str
    data: bytes  # reader-ready bytes
    source_path: str  # grammar: segments joined by "/", fragments after "#"
    text: str | None
    is_context: bool = False  # True only for the email-body context part


@dataclass(frozen=True, slots=True)
class CandidateDocument:
    parts: list[NormalisedPart]  # primary parts first, context part (if any) last
    document_hash: str  # 64 lowercase hex


class UnsupportedReason(StrEnum):
    UNKNOWN_FORMAT = "UNKNOWN_FORMAT"
    EXECUTABLE = "EXECUTABLE"
    LEGACY_OFFICE = "LEGACY_OFFICE"
    ENCRYPTED_PDF = "ENCRYPTED_PDF"
    ENCRYPTED_ARCHIVE = "ENCRYPTED_ARCHIVE"
    ARCHIVE_TOO_DEEP = "ARCHIVE_TOO_DEEP"
    ARCHIVE_TOO_LARGE = "ARCHIVE_TOO_LARGE"
    ARCHIVE_BOMB = "ARCHIVE_BOMB"
    CORRUPT = "CORRUPT"
    EMPTY = "EMPTY"


@dataclass(frozen=True, slots=True)
class UnsupportedNote:
    source_path: str
    media_type: str
    reason: UnsupportedReason
    detail: str = ""  # short, never artifact content


@dataclass(frozen=True, slots=True)
class Normalised:
    documents: list[CandidateDocument]  # always >= 1
    unsupported: list[UnsupportedNote] = field(default_factory=list[UnsupportedNote])


@dataclass(frozen=True, slots=True)
class Unsupported:
    reason: UnsupportedReason
    media_type: str
    notes: list[UnsupportedNote] = field(default_factory=list[UnsupportedNote])


type NormalisationResult = Normalised | Unsupported
