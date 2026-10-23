# s06-intake-poller: Intake poller (mailbox and drop-folder sources, content-hash dedupe, Object Storage)

- Issue: #6
- Wave: 2 (owns `cashapp/pollers/intake/`, `cashapp/integrations/storage/`, `cashapp/integrations/mail/`, `cashapp/integrations/folder/`, `cashapp/data/repositories/artifacts.py`)
- breaking: false

## Story

As AR, I want new remittance artifacts picked up from the mailbox and the drop folder on a configurable interval and turned into work items exactly once, so that nothing is missed or processed twice.

## Context

Poller 1 of exactly 2 (CLAUDE.md non-negotiable 5): a long-running async loop whose only output is new work items + outbox events. research.md: FolderSource is real; MailboxSource sits behind its interface with a fake until s33's decision and mailbox credentials exist. Originals are kept untouched in OCI Object Storage. Normalisation (splitting one email into several remittances) is s34's pure function, called here.

## Acceptance criteria

1. [unit] `cashapp/integrations/storage/base.py`: `ObjectStore` Protocol `put(key, data: bytes, content_type, metadata: dict[str,str]) -> ObjectRef`, `get(key) -> bytes`, `delete(key) -> None`, `exists(key) -> bool`; `OciObjectStore` (OCI SDK via `asyncio.to_thread`, bucket from settings) and `LocalFolderObjectStore` (tests/local); `factory.build_object_store(settings)`. Keys: `artifacts/{sha256}/original`, `artifacts/{sha256}/parts/{n}`.
2. [unit] `cashapp/pollers/intake/sources.py`: `ArtifactSource` Protocol `fetch_new() -> AsyncIterator[IncomingArtifact]`, `mark_processed(ref: SourceRef, outcome: "processed"|"failed") -> None`; `IncomingArtifact` imported from `cashapp/domain/artifacts.py` (s34). `FolderSource` (reads a configured directory, moves files to `processed/` or `failed/` subfolders) and `MailboxSource` interface with `FakeMailboxSource` (in `cashapp/integrations/mail/fake.py`); the real mail adapter follows s33.
3. [integration] One Alembic revision creates `ARTIFACT_PART` (ID, WORK_ITEM_ID, PART_NO, KIND (TEXT|PDF|IMAGE|TABLE|DOCX), MEDIA_TYPE, OBJECT_KEY, SOURCE_PATH, SIZE_BYTES, TEXT_PREVIEW_CHARS, PURGED_AT).
4. [integration] `IntakePoller.run(stop)` loops: read `config.intake().poll_interval_seconds` each cycle (changes apply next cycle), fetch from each source, and for each artifact calls the public `ingest(uow_factory, object_store, artifact, *, source_kind, batch_id: int|None = None, priority: int = 100) -> IngestResult{item_ids, duplicate_of|None}` (reused by s35's backlog import), which does: sha256 of raw bytes → if an item with that CONTENT_HASH exists, record a history row "duplicate received from <source_ref>" on it and mark processed; else store the original, call `normalise(incoming)` (s34), and in ONE transaction create the envelope item (`PARENT_ID` null, STATE=ARCHIVED, note "envelope") when there are ≥2 candidate documents, else a single item; create one child item per candidate document (STAGE=CLASSIFY, STATE=PENDING, PRIORITY=100, CONTENT_HASH = document hash, deduped the same way), its `ARTIFACT_PART` rows (parts stored first), a history row, and a `StageEvent(CLASSIFY)` via `emit`. Then `mark_processed`.
5. [integration] A normalisation `UNSUPPORTED_ARTIFACT` result still creates a work item at STAGE=CLASSIFY, STATE=ESCALATED, LAST_ERROR_CODE=UNSUPPORTED_ARTIFACT (never a silent drop).
6. [unit] A failure on one artifact marks it `failed` and the loop continues; the poller never re-reads a processed file or message (test: second cycle over the same folder yields no new items).
7. [unit] `cashapp/pollers/intake/hooks.py`: `CycleHook` Protocol `async def on_cycle(container, now) -> None` and a module-level `CYCLE_HOOKS: list[CycleHook]` run after each cycle (errors logged, never stop the loop); s41 and s45 append to it.
8. [unit] `ROLE = RoleSpec("intake-poller", "poller", build)` in `cashapp/pollers/intake/__init__.py`.

## Out of scope

Parsing formats (s34), classification (s07), backlog batches (s35), the real mailbox adapter (needs s33's decision and credentials).

## Deps

- s34-artifact-normalisation — `IncomingArtifact` (`cashapp/domain/artifacts.py`) and `normalise(incoming: IncomingArtifact) -> NormalisationResult` where `NormalisationResult = Normalised{documents: list[CandidateDocument{parts: list[NormalisedPart{kind, media_type, data: bytes, source_path, text|None}], document_hash}]} | Unsupported{reason, media_type}` from `cashapp/services/normalise/__init__.py`. plannable (same wave).
- s03-pipeline-runtime — `emit(uow, StageEvent, priority)`, `StageEvent`. plannable (same wave).
- s02-data-layer-foundation — WORK_ITEM columns, `record_history`, `ErrorCode.UNSUPPORTED_ARTIFACT`. plannable.
- s28-runtime-config-service — `config.intake().poll_interval_seconds`. plannable.
- s27-settings-secrets-wiring — `Settings.object_storage`, plus `intake{drop_folder}` (add). plannable.
- s33-spike-mailbox-access — the mailbox decision that the real `MailboxSource` follows; until then `FakeMailboxSource` only. unplannable for the real adapter: needs the client's mail platform; the interface is fixed here.

## Test-support files owned

`LocalFolderObjectStore`, `FakeMailboxSource`, `api/tests/fixtures/artifacts/` (sample emails, PDFs, XLSX, CSV, images, zip, nested .eml/.msg — synthetic, no real names), used by s34, s07, s08, s35.

## Assumptions

- A single-document artifact gets no envelope item.
- Drop folder is a local/mounted path configured by setting `intake.drop_folder`.
