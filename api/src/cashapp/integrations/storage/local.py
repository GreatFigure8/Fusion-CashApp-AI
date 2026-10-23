"""A folder-backed object store for local runs and tests.

Unverified against live behaviour of the OCI store: it mirrors the interface only.
"""

import asyncio
import hashlib
import json
import os
import uuid
from collections.abc import Mapping
from pathlib import Path

from cashapp.integrations.storage.base import InvalidObjectKey, ObjectNotFound, ObjectRef
from cashapp.integrations.storage.keys import validate_key

_META_SUFFIX = ".meta.json"


class LocalFolderObjectStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self._root / key).resolve()
        # Second, independent check: the resolved path must stay under the root.
        if not path.is_relative_to(self._root):
            raise InvalidObjectKey("object key resolves outside the store root")
        return path

    async def put(
        self, key: str, data: bytes, content_type: str, metadata: Mapping[str, str]
    ) -> ObjectRef:
        path = self._path(key)
        meta = json.dumps({"content_type": content_type, "metadata": dict(metadata)})
        await asyncio.to_thread(self._write, path, data, meta)
        return ObjectRef(key=key, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_bytes(payload)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def _write(self, path: Path, data: bytes, meta: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(path, data)
        self._atomic_write(path.with_name(path.name + _META_SUFFIX), meta.encode("utf-8"))

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            raise ObjectNotFound(key) from None

    async def delete(self, key: str) -> None:
        path = self._path(key)

        def remove() -> None:
            path.unlink(missing_ok=True)
            path.with_name(path.name + _META_SUFFIX).unlink(missing_ok=True)

        await asyncio.to_thread(remove)

    async def exists(self, key: str) -> bool:
        path = self._path(key)
        return await asyncio.to_thread(path.is_file)
