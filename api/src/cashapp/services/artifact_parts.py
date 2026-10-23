"""The one shared loader that turns a work item's ARTIFACT_PART rows back into bytes and text."""

import asyncio
from dataclasses import dataclass

from cashapp.data.models.artifacts import ArtifactPart
from cashapp.data.repositories.artifacts import ArtifactPartRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.artifacts import PartKind
from cashapp.integrations.storage.base import ObjectStore
from cashapp.integrations.storage.keys import text_key_for


@dataclass(frozen=True, slots=True)
class LoadedPart:
    part_no: int
    kind: PartKind
    media_type: str
    data: bytes
    text: str | None
    source_path: str | None


class ArtifactPurged(Exception):  # noqa: N818 - pinned name
    def __init__(self, work_item_id: int) -> None:
        super().__init__(f"artifact of work item {work_item_id} has been purged")
        self.work_item_id = work_item_id


async def _load_one(object_store: ObjectStore, part: ArtifactPart) -> LoadedPart:
    data = await object_store.get(part.object_key)
    text: str | None = None
    if part.kind == PartKind.TEXT:
        text = data.decode("utf-8")
    elif part.text_preview_chars is not None:
        text = (await object_store.get(text_key_for(part.object_key))).decode("utf-8")
    return LoadedPart(
        part_no=part.part_no,
        kind=part.kind,
        media_type=part.media_type,
        data=data,
        text=text,
        source_path=part.source_path,
    )


async def load_item_parts(
    uow: UnitOfWork, object_store: ObjectStore, work_item_id: int
) -> list[LoadedPart]:
    """Every part of the item in part order; raises ``ArtifactPurged`` if any was purged."""
    parts = await uow.repo(ArtifactPartRepository).for_item(work_item_id)
    if any(part.purged_at is not None for part in parts):
        raise ArtifactPurged(work_item_id)
    return list(await asyncio.gather(*(_load_one(object_store, part) for part in parts)))
