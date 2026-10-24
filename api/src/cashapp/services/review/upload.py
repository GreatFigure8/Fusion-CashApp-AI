"""Receive files for in-depth review: validate, sanitise, then hand them to the one intake path.

Framework-free: the router passes ``UploadFile`` objects (they satisfy ``ByteSource``) and the chat
tool passes staged bytes. One bad file never fails the others. File content is never logged.
"""

import hashlib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol

from cashapp.data.uow import UowFactory
from cashapp.domain.artifacts import IncomingArtifact
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.principal import Principal
from cashapp.domain.review import (
    MEDIA_TYPES,
    RECEIVED_FOR_REVIEW,
    SniffedType,
    UploadStatus,
    upload_source_ref,
)
from cashapp.domain.work_item import SourceKind
from cashapp.integrations.storage.base import ObjectStore
from cashapp.pollers.intake.ingest import ingest
from cashapp.services.config import RuntimeConfig
from cashapp.services.config_groups import UploadsConfig
from cashapp.services.review.sanitize import (
    MalformedFile,
    image_dimensions,
    inspect_pdf,
    sniff,
    strip_image_metadata,
)
from cashapp.services.review.staging import StagedMeta, StagingError, StagingStore

logger = logging.getLogger(__name__)

_CHUNK: Final = 64 * 1024
_FILENAME_MAX: Final = 200
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")


class ByteSource(Protocol):
    """What the service needs from an uploaded file; ``starlette.UploadFile`` satisfies it."""

    @property
    def filename(self) -> str | None: ...

    @property
    def content_type(self) -> str | None: ...

    async def read(self, size: int = -1, /) -> bytes: ...


@dataclass(frozen=True, slots=True)
class UploadFileResult:
    filename: str
    status: UploadStatus
    item_id: int | None
    message: str


@dataclass(frozen=True, slots=True)
class Quota:
    used: int
    limit: int


@dataclass(frozen=True, slots=True)
class UploadBatchResult:
    files: list[UploadFileResult]
    quota: Quota


@dataclass(frozen=True, slots=True)
class StageBatchResult:
    upload_ids: list[str]
    files: list[UploadFileResult]
    quota: Quota


@dataclass(frozen=True, slots=True)
class _Prepared:
    filename: str
    data: bytes
    kind: SniffedType
    media_type: str


@dataclass(frozen=True, slots=True)
class _Refused:
    result: UploadFileResult


@dataclass(slots=True)
class _Batch:
    cfg: UploadsConfig
    principal: Principal
    used: int
    stored: int = 0
    results: list[UploadFileResult] = field(default_factory=list[UploadFileResult])


def clean_filename(raw: str | None) -> str:
    """The last path segment, without control characters, at most 200 characters."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL.sub("", name).strip()
    return name[:_FILENAME_MAX] or "upload"


def _megabytes(limit: int) -> str:
    value = limit / (1024 * 1024)
    return f"{value:g} MB"


class UploadService:
    def __init__(
        self,
        uow_factory: UowFactory,
        object_store: ObjectStore,
        config: RuntimeConfig,
        clock: Clock | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._store = object_store
        self._config = config
        self._clock: Clock = clock or SystemClock()
        self._staging = StagingStore(object_store)

    # ------------------------------------------------------------------ public

    async def quota(self, principal: Principal) -> Quota:
        cfg = await self._config.uploads()
        return Quota(used=await self._used_today(principal), limit=cfg.daily_per_user)

    async def submit(self, files: Sequence[ByteSource], principal: Principal) -> UploadBatchResult:
        """Validate, sanitise and ingest each file as a MANUAL work item for the uploader."""
        batch = await self._begin(principal)
        for index, source in enumerate(files):
            await self._submit_one(batch, source, index)
        return UploadBatchResult(files=batch.results, quota=self._quota_of(batch))

    async def stage(self, files: Sequence[ByteSource], principal: Principal) -> StageBatchResult:
        """Validate and sanitise each file and park it for a later ``submit_staged``."""
        batch = await self._begin(principal)
        upload_ids: list[str] = []
        for index, source in enumerate(files):
            prepared = await self._prepare_guarded(batch.cfg, source, index)
            if isinstance(prepared, _Refused):
                batch.results.append(prepared.result)
                continue
            try:
                meta = StagedMeta(
                    owner=principal.subject,
                    filename=prepared.filename,
                    content_type=prepared.media_type,
                    sniffed_type=prepared.kind.value,
                    size_bytes=len(prepared.data),
                    sha256=hashlib.sha256(prepared.data).hexdigest(),
                    staged_at=self._clock.now(),
                )
                upload_ids.append(await self._staging.put_staged(prepared.data, meta))
            except Exception as exc:
                logger.warning("staging failed: error_type=%s", type(exc).__name__)
                batch.results.append(_not_stored(prepared.filename))
                continue
            batch.results.append(
                UploadFileResult(prepared.filename, UploadStatus.STORED, None, "Ready to submit.")
            )
        return StageBatchResult(
            upload_ids=upload_ids, files=batch.results, quota=self._quota_of(batch)
        )

    async def submit_staged(
        self, upload_ids: Sequence[str], principal: Principal
    ) -> UploadBatchResult:
        """Ingest previously staged uploads through the same path as a direct upload."""
        batch = await self._begin(principal)
        for index, upload_id in enumerate(upload_ids):
            if index >= batch.cfg.max_files_per_request:
                batch.results.append(
                    UploadFileResult(
                        "upload",
                        UploadStatus.NOT_ALLOWED,
                        None,
                        f"At most {batch.cfg.max_files_per_request} files at a time.",
                    )
                )
                continue
            try:
                data, meta = await self._staging.take_staged(
                    upload_id, principal, self._clock.now(), batch.cfg.stage_ttl_seconds
                )
            except StagingError as exc:
                batch.results.append(
                    UploadFileResult("upload", UploadStatus.NOT_ALLOWED, None, str(exc))
                )
                continue
            result = await self._submit_one(
                batch, _MemorySource(meta.filename, meta.content_type, data), index
            )
            if result.status in (UploadStatus.STORED, UploadStatus.DUPLICATE):
                try:
                    await self._staging.discard(upload_id)
                except Exception as exc:
                    logger.warning("staged cleanup failed: error_type=%s", type(exc).__name__)
        return UploadBatchResult(files=batch.results, quota=self._quota_of(batch))

    # ------------------------------------------------------------------ internals

    async def _begin(self, principal: Principal) -> _Batch:
        cfg = await self._config.uploads()
        return _Batch(cfg=cfg, principal=principal, used=await self._used_today(principal))

    @staticmethod
    def _quota_of(batch: _Batch) -> Quota:
        return Quota(used=batch.used + batch.stored, limit=batch.cfg.daily_per_user)

    async def _used_today(self, principal: Principal) -> int:
        now = self._clock.now()
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)  # UTC day start
        async with self._uow_factory() as uow:
            return await uow.history.count_by_actor_since(
                principal.subject, RECEIVED_FOR_REVIEW, since
            )

    async def _submit_one(self, batch: _Batch, source: ByteSource, index: int) -> UploadFileResult:
        prepared = await self._prepare_guarded(batch.cfg, source, index)
        if isinstance(prepared, _Refused):
            batch.results.append(prepared.result)
            return prepared.result
        if batch.used + batch.stored >= batch.cfg.daily_per_user:
            result = UploadFileResult(
                prepared.filename,
                UploadStatus.QUOTA,
                None,
                f"Daily limit of {batch.cfg.daily_per_user} uploads reached.",
            )
        else:
            result = await self._ingest(batch, prepared)
        if result.status is UploadStatus.STORED:
            batch.stored += 1
        batch.results.append(result)
        return result

    async def _ingest(self, batch: _Batch, prepared: _Prepared) -> UploadFileResult:
        principal = batch.principal
        artifact = IncomingArtifact(
            source_kind=SourceKind.MANUAL,
            source_ref=upload_source_ref(principal.subject),
            filename=prepared.filename,
            content_type=prepared.media_type,
            data=prepared.data,
            received_at=self._clock.now(),
        )
        try:
            outcome = await ingest(
                self._uow_factory,
                self._store,
                artifact,
                source_kind=SourceKind.MANUAL,
                clock=self._clock,
                actor=principal,
                received_payload={
                    "upload": {
                        "filename": prepared.filename,
                        "size_bytes": len(prepared.data),
                        "sniffed_type": prepared.kind.value,
                    }
                },
            )
        except Exception as exc:
            logger.warning("upload ingest failed: error_type=%s", type(exc).__name__)
            return _not_stored(prepared.filename)
        if outcome.item_ids:
            return UploadFileResult(
                prepared.filename, UploadStatus.STORED, outcome.item_ids[0], "Stored for review."
            )
        return UploadFileResult(
            prepared.filename,
            UploadStatus.DUPLICATE,
            outcome.duplicate_of,
            f"Already received as WI-{outcome.duplicate_of}.",
        )

    async def _prepare_guarded(
        self, cfg: UploadsConfig, source: ByteSource, index: int
    ) -> _Prepared | _Refused:
        name = clean_filename(source.filename)
        if index >= cfg.max_files_per_request:
            return _Refused(
                UploadFileResult(
                    name,
                    UploadStatus.NOT_ALLOWED,
                    None,
                    f"At most {cfg.max_files_per_request} files at a time.",
                )
            )
        try:
            return await _prepare(cfg, source, name)
        except Exception as exc:
            logger.warning("upload prepare failed: error_type=%s", type(exc).__name__)
            return _Refused(_not_stored(name))


class _MemorySource:
    """A ``ByteSource`` over bytes that are already in memory."""

    def __init__(self, filename: str | None, content_type: str | None, data: bytes) -> None:
        self.filename = filename
        self.content_type = content_type
        self._data = data
        self._pos = 0

    async def read(self, size: int = -1, /) -> bytes:
        end = len(self._data) if size < 0 else self._pos + size
        chunk = self._data[self._pos : end]
        self._pos += len(chunk)
        return chunk


def _not_stored(name: str) -> UploadFileResult:
    return UploadFileResult(
        name, UploadStatus.NOT_ALLOWED, None, f"{name} could not be stored. Try again."
    )


def _refuse(name: str, status: UploadStatus, message: str) -> _Refused:
    return _Refused(UploadFileResult(name, status, None, message))


async def _read_capped(source: ByteSource, cap: int) -> bytes | None:
    """The whole file, or ``None`` once it is known to exceed ``cap`` (reading stops there)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await source.read(min(_CHUNK, cap + 1 - total))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > cap:
            return None
        chunks.append(chunk)


async def _prepare(cfg: UploadsConfig, source: ByteSource, name: str) -> _Prepared | _Refused:
    data = await _read_capped(source, cfg.max_file_bytes)
    if data is None:
        return _refuse(
            name,
            UploadStatus.TOO_LARGE,
            f"{name} is over {_megabytes(cfg.max_file_bytes)}. The other files were kept.",
        )
    kind = sniff(data[:16])
    if kind is None or kind.value not in cfg.allowed_types:
        return _refuse(
            name, UploadStatus.NOT_ALLOWED, f"{name} is not a PNG, JPG, WEBP or PDF file."
        )
    try:
        if kind is SniffedType.PDF:
            verdict = inspect_pdf(data, cfg.max_pdf_pages)
            if not verdict.ok:
                status = (
                    UploadStatus.TOO_LARGE
                    if verdict.reason and "more than" in verdict.reason
                    else UploadStatus.NOT_ALLOWED
                )
                return _refuse(name, status, f"{name}: {verdict.reason}.")
            clean = data
        else:
            width, height = image_dimensions(data)
            if width * height > cfg.max_pixels:
                return _refuse(
                    name, UploadStatus.TOO_LARGE, f"{name} has too many pixels to read safely."
                )
            clean = strip_image_metadata(data, kind)
    except MalformedFile:
        return _refuse(name, UploadStatus.NOT_ALLOWED, f"{name} is damaged or not a valid file.")
    return _Prepared(filename=name, data=clean, kind=kind, media_type=MEDIA_TYPES[kind])
