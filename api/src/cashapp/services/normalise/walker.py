"""Recursive dispatcher: sniff, budget, depth, handler table, failure containment."""

from collections.abc import Callable

from cashapp.domain.artifacts import UnsupportedNote, UnsupportedReason
from cashapp.services.normalise import sniff
from cashapp.services.normalise.formats import HANDLERS
from cashapp.services.normalise.limits import NormalisationLimits
from cashapp.services.normalise.model import Item, Node, Reject

_CONTAINER_TYPES = frozenset({sniff.ZIP, sniff.EML, sniff.MSG})


class Walker:
    """Walks one artifact tree. A library exception becomes a note, never an exception."""

    def __init__(self, limits: NormalisationLimits) -> None:
        self._limits = limits
        self._used = 0
        self.notes: list[UnsupportedNote] = []
        self.first_media_type: str | None = None

    @property
    def limits(self) -> NormalisationLimits:
        return self._limits

    def remaining(self) -> int:
        return max(self._limits.max_total_bytes - self._used, 0)

    def note(self, path: str, media_type: str, reason: UnsupportedReason, detail: str = "") -> None:
        self.notes.append(UnsupportedNote(path, media_type, reason, detail))

    def check_depth(self, depth: int) -> None:
        if depth > self._limits.max_depth:
            raise Reject(UnsupportedReason.ARCHIVE_TOO_DEEP, f"depth {depth}")

    def _consume(self, size: int) -> None:
        self._used += size
        if self._used > self._limits.max_total_bytes:
            raise Reject(UnsupportedReason.ARCHIVE_TOO_LARGE, "expanded size over limit")

    def guarded(self, path: str, media_type: str, fn: Callable[[], Node]) -> Node | None:
        try:
            return fn()
        except Reject as rejected:
            self.note(path, media_type, rejected.reason, rejected.detail)
        except Exception as exc:
            self.note(path, media_type, UnsupportedReason.CORRUPT, type(exc).__name__)
        return None

    def walk_child(
        self, data: bytes, filename: str, declared: str | None, path: str, depth: int
    ) -> Node | None:
        return self.walk(data, filename, declared, path, depth)

    def walk(
        self, data: bytes, filename: str, declared: str | None, path: str, depth: int = 0
    ) -> Node | None:
        media_type = sniff.sniff_media_type(data, filename, declared)
        if self.first_media_type is None:
            self.first_media_type = media_type

        def run() -> Node:
            if not data:
                raise Reject(UnsupportedReason.EMPTY, "zero bytes")
            self._consume(len(data))
            if media_type in _CONTAINER_TYPES:
                self.check_depth(depth)
            handler = HANDLERS.get(media_type)
            if handler is None:
                raise Reject(UnsupportedReason.UNKNOWN_FORMAT, media_type)
            return handler(Item(data, filename, media_type, path, depth), self)

        return self.guarded(path, media_type, run)
