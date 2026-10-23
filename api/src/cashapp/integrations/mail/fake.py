"""An in-memory mailbox for tests and local runs.

Unverified against a live mailbox: the real adapter follows the s33 mailbox decision. This fake
mirrors the move-to-Processed/Failed convention that adapter is expected to use.
"""

from collections.abc import AsyncIterator, Iterable
from typing import Literal

from cashapp.domain.artifacts import IncomingArtifact


class FakeMailboxSource:
    def __init__(self, messages: Iterable[IncomingArtifact] = (), *, folder: str = "Inbox") -> None:
        self.folder = folder
        self.outcomes: dict[str, Literal["processed", "failed"]] = {}
        self.fail_fetch_with: Exception | None = None
        self._messages: list[IncomingArtifact] = list(messages)

    def add(self, message: IncomingArtifact) -> None:
        self._messages.append(message)

    async def fetch_new(self) -> AsyncIterator[IncomingArtifact]:
        if self.fail_fetch_with is not None:
            raise self.fail_fetch_with
        for message in list(self._messages):
            if message.source_ref in self.outcomes:
                continue
            yield message

    async def mark_processed(self, ref: str, outcome: Literal["processed", "failed"]) -> None:
        self.outcomes[ref] = outcome
