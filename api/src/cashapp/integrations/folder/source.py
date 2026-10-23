"""The drop-folder source: top-level files, moved to processed/ or failed/ once handled."""

import asyncio
import logging
import mimetypes
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from cashapp.domain.artifacts import IncomingArtifact
from cashapp.domain.clock import Clock
from cashapp.domain.work_item import SourceKind

logger = logging.getLogger(__name__)

PROCESSED_DIR = "processed"
FAILED_DIR = "failed"
_CONTENT_TYPES = {".eml": "message/rfc822", ".msg": "application/vnd.ms-outlook"}


@dataclass(frozen=True, slots=True)
class _Candidate:
    path: Path
    mtime: datetime
    size: int


class FolderSource:
    """Reads regular files directly under ``root``; satisfies the ``ArtifactSource`` protocol."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Clock,
        settle_seconds: float = 5.0,
        max_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        self._root = root.resolve()
        self._clock = clock
        self._settle = timedelta(seconds=settle_seconds)
        self._max_bytes = max_bytes

    async def fetch_new(self) -> AsyncIterator[IncomingArtifact]:
        now = self._clock.now()
        candidates = await asyncio.to_thread(self._scan, now)
        for candidate in candidates:
            name = candidate.path.name
            if candidate.size > self._max_bytes:
                logger.warning("drop-folder file over the size limit moved to failed/")
                await self.mark_processed(name, "failed")
                continue
            try:
                data = await asyncio.to_thread(candidate.path.read_bytes)
            except FileNotFoundError:
                continue
            yield IncomingArtifact(
                source_kind=SourceKind.FOLDER,
                source_ref=name,
                filename=name,
                content_type=self._content_type(name),
                data=data,
                received_at=candidate.mtime,
                sender=None,
                subject=None,
            )

    def _scan(self, now: datetime) -> list[_Candidate]:
        found: list[_Candidate] = []
        try:
            entries = list(os.scandir(self._root))
        except FileNotFoundError:
            return []
        for entry in entries:
            name = entry.name
            if name.startswith((".", "~$")):
                continue
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
            stat = entry.stat(follow_symlinks=False)
            mtime = datetime.fromtimestamp(stat.st_mtime, UTC)
            if now - mtime < self._settle:
                continue
            found.append(_Candidate(Path(entry.path), mtime, stat.st_size))
        found.sort(key=lambda c: (c.mtime, c.path.name))
        return found

    @staticmethod
    def _content_type(name: str) -> str:
        suffix = Path(name).suffix.lower()
        if suffix in _CONTENT_TYPES:
            return _CONTENT_TYPES[suffix]
        guessed, _ = mimetypes.guess_type(name)
        return guessed or "application/octet-stream"

    async def mark_processed(self, ref: str, outcome: Literal["processed", "failed"]) -> None:
        source = self._resolve_ref(ref)
        target_dir = self._root / (PROCESSED_DIR if outcome == "processed" else FAILED_DIR)
        await asyncio.to_thread(self._move, source, target_dir)

    def _resolve_ref(self, ref: str) -> Path:
        if not ref or ref in {".", ".."} or "/" in ref or "\\" in ref or os.sep in ref:
            raise ValueError("source ref must be a bare file name")
        path = (self._root / ref).resolve()
        if path.parent != self._root:
            raise ValueError("source ref resolves outside the drop folder")
        return path

    def _move(self, source: Path, target_dir: Path) -> None:
        if not source.exists():
            return  # already moved
        target_dir.mkdir(exist_ok=True)
        target = target_dir / source.name
        if target.exists():
            stamp = self._clock.now().strftime("%Y%m%dT%H%M%S")
            k = 1
            while True:
                target = target_dir / f"{source.stem}.{stamp}-{k}{source.suffix}"
                if not target.exists():
                    break
                k += 1
        source.replace(target)
