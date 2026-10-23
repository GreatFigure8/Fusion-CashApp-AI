"""Chat-staged uploads: sanitised bytes plus a JSON sidecar in object storage, until submitted."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Self

from cashapp.domain.principal import Principal
from cashapp.integrations.storage.base import InvalidObjectKey, ObjectNotFound, ObjectStore
from cashapp.integrations.storage.keys import staged_key, staged_meta_key


class StagingError(Exception):
    """A staged upload cannot be used; the message is safe to show the user."""


@dataclass(frozen=True, slots=True)
class StagedMeta:
    owner: str
    filename: str
    content_type: str
    sniffed_type: str
    size_bytes: int
    sha256: str
    staged_at: datetime

    def to_json(self) -> bytes:
        doc: dict[str, Any] = {
            "owner": self.owner,
            "filename": self.filename,
            "content_type": self.content_type,
            "sniffed_type": self.sniffed_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "staged_at": self.staged_at.isoformat(),
        }
        return json.dumps(doc).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> Self:
        doc = json.loads(raw)
        return cls(
            owner=str(doc["owner"]),
            filename=str(doc["filename"]),
            content_type=str(doc["content_type"]),
            sniffed_type=str(doc["sniffed_type"]),
            size_bytes=int(doc["size_bytes"]),
            sha256=str(doc["sha256"]),
            staged_at=datetime.fromisoformat(doc["staged_at"]).astimezone(UTC),
        )


class StagingStore:
    def __init__(self, object_store: ObjectStore) -> None:
        self._store = object_store

    async def put_staged(self, data: bytes, meta: StagedMeta) -> str:
        upload_id = uuid.uuid4().hex
        await self._store.put(
            staged_key(upload_id), data, meta.content_type, {"sha256": meta.sha256}
        )
        await self._store.put(staged_meta_key(upload_id), meta.to_json(), "application/json", {})
        return upload_id

    async def take_staged(
        self, upload_id: str, principal: Principal, now: datetime, ttl_seconds: int
    ) -> tuple[bytes, StagedMeta]:
        """The staged bytes and metadata; refuses another user's upload and an expired one."""
        try:
            meta = StagedMeta.from_json(await self._store.get(staged_meta_key(upload_id)))
            data = await self._store.get(staged_key(upload_id))
        except (ObjectNotFound, InvalidObjectKey, ValueError, KeyError) as exc:
            raise StagingError("That upload was not found or has expired.") from exc
        if meta.owner != principal.subject:
            raise StagingError("That upload is not yours.")
        if now > meta.staged_at + timedelta(seconds=ttl_seconds):
            await self.discard(upload_id)
            raise StagingError("That upload has expired. Attach it again.")
        return data, meta

    async def discard(self, upload_id: str) -> None:
        await self._store.delete(staged_key(upload_id))
        await self._store.delete(staged_meta_key(upload_id))
