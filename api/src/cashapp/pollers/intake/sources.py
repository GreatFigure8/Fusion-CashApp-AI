"""The intake source interfaces and the list of sources the poller reads."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal, Protocol

from cashapp.domain.artifacts import IncomingArtifact
from cashapp.domain.clock import SystemClock
from cashapp.integrations.folder import FolderSource
from cashapp.settings import Settings

type SourceRef = str
type SourceOutcome = Literal["processed", "failed"]


class ArtifactSource(Protocol):
    def fetch_new(self) -> AsyncIterator[IncomingArtifact]:
        """An async generator over artifacts not yet marked processed or failed."""
        ...

    async def mark_processed(self, ref: SourceRef, outcome: SourceOutcome) -> None: ...


class MailboxSource(ArtifactSource, Protocol):
    folder: str


def build_sources(settings: Settings) -> list[ArtifactSource]:
    """The sources the poller reads. The real mailbox adapter is appended here after s33."""
    return [FolderSource(Path(settings.intake.drop_folder), clock=SystemClock())]


__all__ = [
    "ArtifactSource",
    "FolderSource",
    "MailboxSource",
    "SourceOutcome",
    "SourceRef",
    "build_sources",
]
