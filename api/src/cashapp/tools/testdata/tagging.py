"""Tagging: every generated record is findable and recognisably test data.

A record is ours only when its number starts with ``CATD-<tag>-`` *and* its comments carry
``cashapp-testdata:<tag>``. Cleanup requires both, so it can never point at untagged data.
"""

from __future__ import annotations

import re
from typing import Final, Literal

TAG_PATTERN: Final = r"^[A-Z0-9]{1,8}$"
NUMBER_PREFIX: Final = "CATD"
MARKER_PREFIX: Final = "cashapp-testdata:"

NumberKind = Literal["INV", "CM", "RCPT"]


def validate_tag(tag: str) -> str:
    """Upper-case the tag and refuse anything but 1 to 8 letters or digits."""
    upper = tag.upper()
    if re.fullmatch(TAG_PATTERN, upper) is None:
        raise ValueError(f"invalid tag {tag!r}: use 1 to 8 letters or digits")
    return upper


def number_prefix(tag: str) -> str:
    return f"{NUMBER_PREFIX}-{validate_tag(tag)}-"


def tagged_number(tag: str, kind: NumberKind, n: int) -> str:
    """``CATD-<tag>-<kind>-<nnn>``, e.g. ``CATD-T001-INV-001``."""
    if n < 1:
        raise ValueError("n must be at least 1")
    return f"{number_prefix(tag)}{kind}-{n:03d}"


def tag_marker(tag: str) -> str:
    return f"{MARKER_PREFIX}{validate_tag(tag)}"


def is_tagged(number: str, comments: str | None, tag: str) -> bool:
    """True only when both the number prefix and the comments marker are present."""
    if comments is None:
        return False
    return number.startswith(number_prefix(tag)) and tag_marker(tag) in comments
