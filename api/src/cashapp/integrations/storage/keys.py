"""Content-addressed object keys. Every store validates a key before touching storage."""

import re

from cashapp.integrations.storage.base import InvalidObjectKey

_KEY_RE = re.compile(r"^artifacts/[0-9a-f]{64}/(original|parts/[1-9][0-9]{0,3}(\.txt)?)$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _check_hash(value: str) -> str:
    if not _SHA_RE.fullmatch(value):
        raise InvalidObjectKey("a content hash must be 64 lowercase hex characters")
    return value


def original_key(sha256: str) -> str:
    """The untouched original artifact, keyed by the sha256 of its raw bytes."""
    return validate_key(f"artifacts/{_check_hash(sha256)}/original")


def part_key(document_hash: str, part_no: int) -> str:
    """Part ``part_no`` (1-based) of the document with ``document_hash``."""
    return validate_key(f"artifacts/{_check_hash(document_hash)}/parts/{part_no}")


def part_text_key(document_hash: str, part_no: int) -> str:
    """The extracted text of a part, stored as a sibling UTF-8 object."""
    return text_key_for(part_key(document_hash, part_no))


def text_key_for(object_key: str) -> str:
    return validate_key(f"{validate_key(object_key)}.txt")


def validate_key(key: str) -> str:
    """Return ``key`` or raise ``InvalidObjectKey``."""
    if not _KEY_RE.fullmatch(key):
        raise InvalidObjectKey("object key does not match the artifact key layout")
    return key
