"""Identifier scanner: finds real-looking identifiers in text, files and fixture output.

Two kinds of check. A denylist (terms kept outside the repo) is matched case-insensitively on word
boundaries. Structural patterns catch emails, IBAN-like codes and long account-like digit runs that
do not carry an anonymised marker. Findings carry a masked excerpt only, so CI output never leaks
the value that was found.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Final

ANONYMISED_MARKERS: Final[tuple[str, ...]] = (
    "Customer-",
    "INV-",
    "RCPT-",
    "REF-",
    "PO-",
    "SO-",
    "ERS-",
    "MSG-",
    "BANK-",
    "BU-",
    "SITE-",
    "TERMS-",
)

EMAIL_PATTERN: Final = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
_EMAIL: Final = re.compile(EMAIL_PATTERN)
_IBAN: Final = re.compile(
    r"\b[A-Z]{2}\d{2}(?:[A-Z0-9]{11,30}|(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?)\b"
)
# Not a word/decimal/thousands part, a MIME boundary (``=``), a Message-ID local part (``@``) or a
# PDF cross-reference entry (offset, generation, ``n``).
_ACCOUNT: Final = re.compile(r"(?<![\w.,=-])\d{8,}(?![\w.,=@])(?! \d{5} [fn](?![A-Za-z]))")
_ANONYMISED_ACCOUNT: Final = re.compile(r"^(?:9\d{5}|9\d{7}|9\d{9})$")

_RESERVED_EMAIL_DOMAINS: Final = frozenset({"example.com", "example.org", "example.net"})
_RESERVED_EMAIL_SUFFIXES: Final = (".example", ".test", ".invalid", ".localhost")
_ALLOWED_EMAILS: Final = frozenset({"noreply@anthropic.com"})

_SKIPPED_DIRS: Final = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "node_modules",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    }
)
_MAX_FILE_BYTES: Final = 5 * 1024 * 1024
_BINARY_PROBE: Final = 8192
_MIN_TERM_LENGTH: Final = 3


class FindingKind(StrEnum):
    DENYLIST = "denylist"
    EMAIL = "email"
    IBAN = "iban"
    ACCOUNT_NUMBER = "account_number"


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    line: int  # 1-based
    column: int  # 1-based
    length: int
    masked: str  # first char + "***" + (length); never the full match
    path: str | None = None  # repo-relative, set by scan_paths

    def render(self) -> str:
        where = f"{self.path}:" if self.path else ""
        return f"{where}{self.line}:{self.column} {self.kind.value} {self.masked}"


def _mask(match_text: str) -> str:
    return f"{match_text[:1]}***({len(match_text)})"


def _is_reserved_email(address: str) -> bool:
    lowered = address.lower()
    if lowered in _ALLOWED_EMAILS:
        return True
    domain = lowered.rsplit("@", 1)[-1]
    if domain in _RESERVED_EMAIL_DOMAINS or domain.endswith(_RESERVED_EMAIL_SUFFIXES):
        return True
    return any(domain.endswith(f".{reserved}") for reserved in _RESERVED_EMAIL_DOMAINS)


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(index + 1 for index, char in enumerate(text) if char == "\n")
    return starts


def _locate(starts: list[int], offset: int) -> tuple[int, int]:
    row = bisect_right(starts, offset) - 1
    return row + 1, offset - starts[row] + 1


def _term_pattern(term: str) -> re.Pattern[str] | None:
    normalised = " ".join(unicodedata.normalize("NFKC", term).split())
    if len(normalised) < _MIN_TERM_LENGTH:
        return None
    body = re.escape(normalised).replace(r"\ ", r"\s+")
    head = r"(?<![^\W_])" if normalised[0].isalnum() else ""
    tail = r"(?![^\W_])" if normalised[-1].isalnum() else ""
    return re.compile(head + body + tail, re.IGNORECASE)


def scan_for_identifiers(text: str, denylist: Sequence[str] = ()) -> list[Finding]:
    """All findings in ``text``, ordered by position."""
    starts = _line_starts(text)
    found: list[tuple[int, Finding]] = []

    def add(kind: FindingKind, start: int, matched: str) -> None:
        line, column = _locate(starts, start)
        found.append((start, Finding(kind, line, column, len(matched), _mask(matched))))

    for term in denylist:
        pattern = _term_pattern(term)
        if pattern is None:
            continue
        for match in pattern.finditer(text):
            add(FindingKind.DENYLIST, match.start(), match.group(0))
    for match in _EMAIL.finditer(text):
        if not _is_reserved_email(match.group(0)):
            add(FindingKind.EMAIL, match.start(), match.group(0))
    for match in _IBAN.finditer(text):
        add(FindingKind.IBAN, match.start(), match.group(0))
    for match in _ACCOUNT.finditer(text):
        digits = match.group(0)
        if _ANONYMISED_ACCOUNT.match(digits):
            continue
        before = text[: match.start()]
        if any(before.endswith(marker) for marker in ANONYMISED_MARKERS):
            continue
        add(FindingKind.ACCOUNT_NUMBER, match.start(), digits)
    found.sort(key=lambda item: (item[0], item[1].kind.value))
    return [finding for _start, finding in found]


def load_denylist(path: Path) -> tuple[str, ...]:
    """One term per line; ``#`` comments and blanks skipped; terms under 3 characters dropped."""
    terms: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        term = raw.strip()
        if not term or term.startswith("#") or len(term) < _MIN_TERM_LENGTH:
            continue
        terms.append(term)
    return tuple(terms)


def _is_binary(path: Path) -> bool:
    with path.open("rb") as handle:
        return b"\x00" in handle.read(_BINARY_PROBE)


def _walk(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    for child in sorted(root.iterdir()):
        if child.is_dir():
            if child.name not in _SKIPPED_DIRS:
                yield from _walk(child)
        elif child.is_file():
            yield child


def iter_scannable_files(roots: Sequence[Path]) -> Iterator[Path]:
    """Text files under ``roots``: skips caches, ``.pyc``, binaries and files over 5 MiB."""
    for root in roots:
        if not root.exists():
            continue
        for path in _walk(root):
            if path.suffix == ".pyc":
                continue
            if path.stat().st_size > _MAX_FILE_BYTES or _is_binary(path):
                continue
            yield path


def _relative(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def scan_paths(roots: Sequence[Path], denylist: Sequence[str] = (), *, base: Path) -> list[Finding]:
    """Scan every scannable file under ``roots``; findings carry paths relative to ``base``."""
    findings: list[Finding] = []
    for path in iter_scannable_files(roots):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = _relative(path, base)
        findings.extend(replace(item, path=rel) for item in scan_for_identifiers(text, denylist))
    return findings
