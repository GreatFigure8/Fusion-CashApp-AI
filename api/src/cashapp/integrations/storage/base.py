"""The object-store interface: where raw artifacts and their normalised parts live."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ObjectRef:
    key: str
    size_bytes: int
    sha256: str
    etag: str | None = None


class ObjectNotFound(KeyError):  # noqa: N818 - pinned name
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class InvalidObjectKey(ValueError):  # noqa: N818 - pinned name
    """The key is not one of the content-addressed shapes in ``keys.py``."""


class ObjectStore(Protocol):
    async def put(
        self, key: str, data: bytes, content_type: str, metadata: Mapping[str, str]
    ) -> ObjectRef: ...

    async def get(self, key: str) -> bytes:
        """The object's bytes; raises ``ObjectNotFound`` when absent."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the object; deleting an absent object is not an error."""
        ...

    async def exists(self, key: str) -> bool: ...
