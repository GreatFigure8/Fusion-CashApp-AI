"""The HMAC key: read from a file outside the repo, created on request, never printed."""

from __future__ import annotations

import contextlib
import hashlib
import os
import secrets
from pathlib import Path
from typing import Final

KEY_MIN_BYTES: Final = 32
_SYNTHETIC_PREFIX: Final = b"cashapp-synthetic-fixture-key\x00"
_KEY_ID_PREFIX: Final = b"cashapp-anonymise-key-id\x00"


class KeyFileError(Exception):
    """The key file is missing, unreadable or too short."""


def load_key(path: Path) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise KeyFileError("key file cannot be read") from exc
    if len(data) < KEY_MIN_BYTES:
        raise KeyFileError(f"key file must hold at least {KEY_MIN_BYTES} bytes")
    return data


def init_key(path: Path) -> bool:
    """Create the key file with 32 random bytes. Never overwrites; returns whether it created."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(secrets.token_bytes(KEY_MIN_BYTES))
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return True


def synthetic_key(seed: int) -> bytes:
    """Deliberately public key for the fake data, so committed fixtures are reproducible."""
    return hashlib.sha256(_SYNTHETIC_PREFIX + str(seed).encode("ascii")).digest()


def key_id(key: bytes) -> str:
    """Short fingerprint that identifies which key produced a fixture set, without exposing it."""
    return hashlib.sha256(_KEY_ID_PREFIX + key).hexdigest()[:12]
