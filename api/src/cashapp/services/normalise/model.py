"""Internal walk-tree types shared by the walker, the format handlers and the assembler."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from cashapp.domain.artifacts import NormalisedPart, PartKind, UnsupportedReason
from cashapp.services.normalise.limits import NormalisationLimits


class Reject(Exception):  # noqa: N818 - a control-flow signal, not an error
    """Raised by a handler for a piece that cannot be normalised."""

    def __init__(self, reason: UnsupportedReason, detail: str = "") -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Item:
    """One piece handed to a format handler."""

    data: bytes
    filename: str
    media_type: str
    path: str
    depth: int


@dataclass(frozen=True, slots=True)
class Leaf:
    """One standalone document: its parts are one candidate."""

    parts: list[NormalisedPart]


@dataclass(frozen=True, slots=True)
class EmailNode:
    """An email: body plus attachment sub-trees."""

    path: str
    stripped: str  # stripped body text only (used for the remittance heuristic)
    text: str  # header lines + stripped body (what goes into the part)
    children: list["Node"] = field(default_factory=list["Node"])


@dataclass(frozen=True, slots=True)
class Container:
    """A zip archive: its members are independent."""

    children: list["Node"] = field(default_factory=list["Node"])


type Node = Leaf | EmailNode | Container


class WalkContext(Protocol):
    """What a format handler may ask of the walker."""

    @property
    def limits(self) -> NormalisationLimits: ...

    def remaining(self) -> int: ...

    def note(
        self, path: str, media_type: str, reason: UnsupportedReason, detail: str = ""
    ) -> None: ...

    def check_depth(self, depth: int) -> None: ...

    def walk_child(
        self, data: bytes, filename: str, declared: str | None, path: str, depth: int
    ) -> Node | None: ...

    def guarded(self, path: str, media_type: str, fn: Callable[[], Node]) -> Node | None: ...


type Handler = Callable[[Item, WalkContext], Node]


def unique_name(name: str, seen: set[str]) -> str:
    """Return `name`, suffixed with ~n when already used, and record it."""
    candidate = name
    n = 1
    while candidate in seen:
        n += 1
        candidate = f"{name}~{n}"
    seen.add(candidate)
    return candidate


def text_part(
    kind: PartKind, media_type: str, text: str, path: str, *, is_context: bool = False
) -> NormalisedPart:
    """A TEXT or TABLE part: UTF-8 bytes and the same text."""
    return NormalisedPart(kind, media_type, text.encode("utf-8"), path, text, is_context)
