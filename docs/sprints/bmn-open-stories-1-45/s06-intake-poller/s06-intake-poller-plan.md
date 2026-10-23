# Plan: s06-intake-poller

Issue #6. Wave 2. Paths: `cashapp/` = `api/src/cashapp/`. Poller 1 of exactly 2 (CLAUDE.md non-negotiable 5).

## Standards followed

- CLAUDE.md: the database is the system of record; one transaction per state change + history + outbox event (`emit`, s03); dedupe at intake on content hash; raw artifacts kept untouched in OCI Object Storage (Ashburn); integrations behind interfaces; the poller is a long-running async loop (not a scheduled job) whose only output is new work items and their events; interval read from runtime config every cycle.
- research.md: exactly two implementations per external system (`OciObjectStore` real + `LocalFolderObjectStore` fake; `MailboxSource` fake now, real adapter after s33). Fakes record "unverified against live" in their docstring.
- s02 data rules: lowercase SQLAlchemy names, upper snake physical objects, identity PK, enum columns `VARCHAR2(40)` with no CHECK, explicit constraint names ≤ 30 chars, repositories never commit, no `sqlalchemy` import outside `cashapp/data/` and `alembic/`.
- `python-web-app:building-python-web-apps`: logic in services, external SDKs isolated in an integration module, blocking SDK calls via `asyncio.to_thread`.
- `python-library-quality:guarding-destructive-operations` (moves/deletes): refs and keys validated structurally plus resolved-path containment before any move/write/delete.
- PII (CLAUDE.md, s29): never log artifact bytes, subjects, senders or filenames' contents; log `work_item_id`, content hash and source kind only. Object metadata carries no PII (`sha256`, `source_kind` only). Loggers are stdlib `logging.getLogger(__name__)`, so s29's JSON handler and `RedactionFilter` apply without importing s29.
- Gates for the coder: `uv run ruff check . && uv run ruff format --check .`, `uv run pyright` only.

## Files to touch (all new, file-disjoint from other stories)

| Path | Content |
|---|---|
| `cashapp/integrations/storage/__init__.py` | re-exports `ObjectStore`, `ObjectRef`, `ObjectNotFound`, `InvalidObjectKey` |
| `cashapp/integrations/storage/base.py` | `ObjectStore` Protocol, `ObjectRef`, errors |
| `cashapp/integrations/storage/keys.py` | `original_key`, `part_key`, `part_text_key`, `validate_key` |
| `cashapp/integrations/storage/oci.py` | `OciObjectStore` (OCI SDK, `asyncio.to_thread`) |
| `cashapp/integrations/storage/local.py` | `LocalFolderObjectStore` (tests/local) |
| `cashapp/integrations/storage/factory.py` | `build_object_store(settings) -> ObjectStore` |
| `cashapp/integrations/mail/__init__.py` | re-exports `FakeMailboxSource` |
| `cashapp/integrations/mail/fake.py` | `FakeMailboxSource` |
| `cashapp/integrations/folder/__init__.py` | re-exports `FolderSource` |
| `cashapp/integrations/folder/source.py` | `FolderSource` |
| `cashapp/data/models/artifacts.py` | ORM `ArtifactPart` (table `artifact_part`); auto-loaded by s02's `load_all_models()` |
| `cashapp/data/repositories/artifacts.py` | `ArtifactPartRepository`, `is_unique_violation` |
| `cashapp/services/artifact_parts.py` | `LoadedPart`, `load_item_parts` (the one shared part loader for s07/s08) |
| `cashapp/pollers/intake/__init__.py` | `ROLE = RoleSpec("intake-poller", "poller", build)`, `build` |
| `cashapp/pollers/intake/sources.py` | `SourceRef`, `SourceOutcome`, `ArtifactSource`, `MailboxSource` Protocols, `build_sources(settings)`; re-exports `FolderSource` |
| `cashapp/pollers/intake/ingest.py` | `IngestResult`, `ingest(...)` |
| `cashapp/pollers/intake/poller.py` | `IntakePoller` |
| `cashapp/pollers/intake/hooks.py` | `CycleHook`, `CYCLE_HOOKS`, `run_cycle_hooks` |
| `api/alembic/versions/s06_artifact_part.py` | the one revision |
| `api/tests/fixtures/artifacts/build_fixtures.py` + generated files (listed below) | synthetic fixtures (owned test support) |
| `api/tests/support/artifacts.py` | `fixture_path(name)`, `fixture_bytes(name)`, `make_incoming(name, **overrides)` |
| tests in the TEST PLAN | written and run in step 5 only |

Not touched: `settings.py` (s27 already has `object_storage` and `intake.drop_folder`), `main.py`, lockfiles (deps `oci`, `pillow`, `openpyxl`, `pypdf`, `python-docx` already pinned by s01), `cashapp/data/uow.py` (reached through `uow.repo(ArtifactPartRepository)`), `work_items.py`/`history.py` (s02), `cashapp/domain/artifacts.py` and `cashapp/services/normalise/` (s34), `cashapp/pipeline/*` (s03).

## Design

### Object keys (`keys.py`)

- `original_key(sha256) = "artifacts/{sha256}/original"` (sha256 of the raw artifact bytes).
- `part_key(document_hash, n) = "artifacts/{document_hash}/parts/{n}"`, `n` 1-based within the document.
- `part_text_key(document_hash, n) = "artifacts/{document_hash}/parts/{n}.txt"`: the part's extracted `text` (UTF-8) when `NormalisedPart.text` is set and the part is not itself TEXT (for TEXT parts `data` is the text). `ARTIFACT_PART` has no text column, so this key is derivable: `text_key_for(object_key) = object_key + ".txt"`.
- `validate_key`: matches `^artifacts/[0-9a-f]{64}/(original|parts/[1-9][0-9]{0,3}(\.txt)?)$`; anything else raises `InvalidObjectKey`. Every store method validates first. Keys are content-addressed, so a retried put rewrites identical bytes (idempotent).

### `OciObjectStore`

- `oci.object_storage.ObjectStorageClient`; signer = resource principal when `OCI_RESOURCE_PRINCIPAL_VERSION` is set, else `oci.config.from_file()` (same rule as s27's `VaultSecretSource.from_environment`), region forced to `settings.object_storage.region` (`us-ashburn-1`).
- `put` → `put_object(namespace, bucket, key, data, content_type=, opc_meta=metadata, content_md5=)`; `get` → `get_object(...).data.content`; `delete` → `delete_object` (404 swallowed: idempotent); `exists` → `head_object` (404 → False). All via `asyncio.to_thread`. `oci.exceptions.ServiceError` 404 on `get` → `ObjectNotFound(key)`; others propagate.
- Docstring: "unverified against live until a DEV bucket probe (`-m live`) passes".

### `LocalFolderObjectStore(root: Path)`

Writes `root/<key>` atomically (temp file + `os.replace`) and metadata to `root/<key>.meta.json`; resolved path must stay under `root` (second, independent check after `validate_key`). File I/O via `asyncio.to_thread`.

### Factory

`build_object_store(settings)`: `settings.env == "local"` → `LocalFolderObjectStore(Path(settings.intake.drop_folder) / ".objectstore")`; otherwise `OciObjectStore.from_settings(settings.object_storage)`. (s30 resolves it by import path `cashapp.integrations.storage.factory:build_object_store`.)

### Sources

- `FolderSource(root: Path, *, clock: Clock, settle_seconds: float = 5.0, max_bytes: int = 50 * 1024 * 1024)`:
  - `fetch_new()` lists **top-level regular files only** (no symlinks, no dirs, skips names starting with `.` or `~$`, and files whose mtime is within `settle_seconds` of `clock.now()` so half-copied files are not read), sorted by (mtime, name). Reads bytes via `asyncio.to_thread`. Yields `IncomingArtifact(source_kind=FOLDER, source_ref=<file name>, filename=<file name>, content_type=<guessed: .eml → message/rfc822, .msg → application/vnd.ms-outlook, else mimetypes, else application/octet-stream>, data, received_at=<mtime UTC>, sender=None, subject=None)`.
  - Files over `max_bytes` are moved straight to `failed/` with a warning (visible, never silently dropped) and not yielded.
  - `mark_processed(ref, outcome)` moves `root/ref` to `root/processed/` or `root/failed/` (created on demand). `ref` must be a bare file name (no separator, not `.`/`..`) and the resolved path must be inside `root`, else `ValueError`. Name collision → `<stem>.<UTC yyyymmddTHHMMSS>-<k><suffix>`. A missing file (already moved) is a no-op.
- `FakeMailboxSource(messages: Iterable[IncomingArtifact] = (), *, folder: str = "Inbox")`: `add(msg)`, `fetch_new()` yields messages not yet marked (mirrors s33's move-to-`CashApp/Processed`/`CashApp/Failed` convention), `outcomes: dict[SourceRef, SourceOutcome]`, `fail_fetch_with: Exception | None`. Each message is one `IncomingArtifact` with raw RFC 822 bytes, `content_type="message/rfc822"`, `source_kind=MAILBOX`.
- `build_sources(settings) -> list[ArtifactSource]` returns `[FolderSource(Path(settings.intake.drop_folder), clock=SystemClock())]`. The real mailbox adapter (s33 follow-up) is appended here when it exists; no flag.

### `ingest` (the one intake path; s35 reuses it)

```
raw_hash = sha256(artifact.data)
1. existing = work_items.by_content_hash(raw_hash)  → duplicate: record_history(existing, DECISION,
   "duplicate received from <source_kind>:<source_ref>"), commit, return IngestResult([], duplicate_of=existing.id)
2. put(original_key(raw_hash), data, content_type, {"sha256": raw_hash, "source_kind": kind})   # before the DB txn
3. result = await asyncio.to_thread(normaliser, artifact)          # normaliser defaults to s34 normalise
4a. Unsupported → ONE txn: item(content_hash=raw_hash, artifact_key=original, stage=CLASSIFY, state=ESCALATED,
    last_error_code=UNSUPPORTED_ARTIFACT, last_error_detail={"reason","media_type"}, escalation_summary=reason,
    priority, batch_id) + history(STAGE_TRANSITION → CLASSIFY/ESCALATED, error_code). No event (escalated items wait
    for a person). Commit. Return IngestResult([id], None).
4b. Normalised → per document: dup = by_content_hash(document_hash) (also skip a hash repeated inside this artifact).
    new_docs = non-duplicates. If new_docs is empty: history "duplicate received" on each dup, commit,
    return IngestResult([], duplicate_of=first dup id).
    Store every part of new_docs (part_key, and part_text_key when text) — before the txn.
    ONE txn:
      - envelope when len(result.documents) >= 2: item(parent_id=None, content_hash=raw_hash, stage=INTAKE,
        state=ARCHIVED, artifact_key=original) + history(DECISION, "envelope", payload {documents: N, new: M}).
      - per new doc: item(parent_id=envelope.id|None, content_hash=document_hash (single-doc: document_hash too),
        artifact_key=original_key(raw_hash), stage=CLASSIFY, state=PENDING, priority, batch_id, source_kind,
        source_ref) ; ARTIFACT_PART rows (part_no 1..n, kind, media_type, object_key, source_path, size_bytes,
        text_preview_chars=len(text) or None) ; history(STAGE_TRANSITION → CLASSIFY/PENDING, payload
        {parts, document_hash, parent_id}) ; emit(uow, StageEvent(CLASSIFY), priority=priority).
      - per duplicate doc: history "duplicate received from …" on the existing item.
    Commit. Return IngestResult(item_ids=[child ids], duplicate_of=None, envelope_id=...).
5. Unique-key race (another process inserted the same hash between check and commit; `is_unique_violation(exc)`):
   roll back, re-run steps 1–4 once (it then lands in the duplicate branch).
```

- `mark_processed` is the poller's job (after `ingest` returns), not `ingest`'s, so s35 can drive its own source.
- A crash between commit and `mark_processed` means the next cycle re-reads that file; step 1 catches it (one extra "duplicate received" history row, no new item).
- The single-document item's `CONTENT_HASH` is the **document hash** (not the raw hash) so the same PDF arriving alone or inside an email dedupes both ways; a re-delivery of the same raw single-document artifact is caught at step 4b (normalisation is deterministic, s34 AC6). Envelope and unsupported items carry the raw hash.
- `StageEvent` is built as `StageEvent(event_id=uuid4(), work_item_id=id, stage=Stage.CLASSIFY, attempt=0, not_before=None, trace_id=uuid4().hex, emitted_at=clock.now())` unless s03 pins a constructor helper, in which case the coder uses it.

### `IntakePoller`

```python
class IntakePoller:  # satisfies s03 Runnable
    def __init__(self, *, container: Container, sources: Sequence[ArtifactSource], object_store: ObjectStore,
                 hooks: Sequence[CycleHook] | None = None,  # None -> the live CYCLE_HOOKS list
                 normaliser: Normaliser = normalise) -> None
    async def run(self, stop: asyncio.Event) -> None
    async def run_cycle(self) -> CycleStats          # one pass; tests call it directly
    def state(self) -> RoleState
```

- `run`: loop until `stop` is set: `cfg = await container.config.snapshot()`; `interval = max(1, cfg.intake().poll_interval_seconds)` (read each cycle; a change applies next cycle); `await run_cycle()`; then `await asyncio.wait_for(stop.wait(), interval)` (TimeoutError → next cycle). Status `running`; `degraded` with a detail when the last cycle had a source error; `stopped` on exit. `last_activity_at` = end of the last cycle.
- `run_cycle`: for each source, `async for artifact in source.fetch_new()` (stops between artifacts once `stop` is set): `ingest(...)` then `mark_processed(ref, "processed")`; any exception → log `exception type + source kind + sha256` (no content), `mark_processed(ref, "failed")` (its own failure logged too), continue. An exception from `fetch_new` itself is logged and the next source runs. After all sources: `await run_cycle_hooks(hooks, container, clock.now())`.
- Artifacts are ingested one at a time (natural back-pressure; ~2,500 mails/day is well inside one loop).
- `CycleStats{ingested: int, duplicates: int, failed: int, source_errors: int}` returned and logged.

### Hooks

```python
class CycleHook(Protocol):
    async def on_cycle(self, container: Container, now: datetime) -> None: ...
CYCLE_HOOKS: list[CycleHook] = []    # s41 / s45 append at import of their own module
async def run_cycle_hooks(hooks: Sequence[CycleHook], container: Container, now: datetime) -> None
    # each hook awaited in order; exceptions logged with the hook's class name and swallowed
```

This story imports nothing from s41/s45. They append to `CYCLE_HOOKS` from their own package `__init__`, which s30's discovery imports, so no file here is edited later. Recorded as an assumption for those planners.

## Interfaces provided (pinned)

```python
# cashapp/integrations/storage/base.py
@dataclass(frozen=True, slots=True)
class ObjectRef: key: str; size_bytes: int; sha256: str; etag: str | None = None
class ObjectNotFound(KeyError): key: str
class InvalidObjectKey(ValueError): ...
class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str, metadata: Mapping[str, str]) -> ObjectRef: ...
    async def get(self, key: str) -> bytes: ...          # ObjectNotFound when absent
    async def delete(self, key: str) -> None: ...        # idempotent
    async def exists(self, key: str) -> bool: ...

# cashapp/integrations/storage/keys.py
def original_key(sha256: str) -> str
def part_key(document_hash: str, part_no: int) -> str
def part_text_key(document_hash: str, part_no: int) -> str
def text_key_for(object_key: str) -> str                 # object_key + ".txt"
def validate_key(key: str) -> str                        # returns key or raises InvalidObjectKey

# cashapp/integrations/storage/oci.py / local.py
class OciObjectStore:  # ObjectStore
    def __init__(self, client: ObjectStorageClientLike, *, namespace: str, bucket: str) -> None
    @classmethod
    def from_settings(cls, s: ObjectStorageSettings) -> "OciObjectStore"
class LocalFolderObjectStore:  # ObjectStore
    def __init__(self, root: Path) -> None
# cashapp/integrations/storage/factory.py
def build_object_store(settings: Settings) -> ObjectStore

# cashapp/pollers/intake/sources.py
SourceRef: TypeAlias = str
SourceOutcome: TypeAlias = Literal["processed", "failed"]
class ArtifactSource(Protocol):
    def fetch_new(self) -> AsyncIterator[IncomingArtifact]: ...     # async generator
    async def mark_processed(self, ref: SourceRef, outcome: SourceOutcome) -> None: ...
class MailboxSource(ArtifactSource, Protocol):
    folder: str
def build_sources(settings: Settings) -> list[ArtifactSource]
# cashapp/integrations/folder/source.py
class FolderSource:  # ArtifactSource
    def __init__(self, root: Path, *, clock: Clock, settle_seconds: float = 5.0, max_bytes: int = 52_428_800) -> None
# cashapp/integrations/mail/fake.py
class FakeMailboxSource:  # MailboxSource
    def __init__(self, messages: Iterable[IncomingArtifact] = (), *, folder: str = "Inbox") -> None
    def add(self, message: IncomingArtifact) -> None
    outcomes: dict[str, Literal["processed", "failed"]]
    fail_fetch_with: Exception | None

# cashapp/pollers/intake/ingest.py
Normaliser: TypeAlias = Callable[[IncomingArtifact], NormalisationResult]
@dataclass(frozen=True, slots=True)
class IngestResult:
    item_ids: list[int]            # items that entered the pipeline (or the one ESCALATED unsupported item)
    duplicate_of: int | None       # set only when nothing new was created
    envelope_id: int | None = None
async def ingest(uow_factory: UowFactory, object_store: ObjectStore, artifact: IncomingArtifact, *,
                 source_kind: SourceKind, batch_id: int | None = None, priority: int = PRIORITY_LIVE,
                 clock: Clock | None = None, normaliser: Normaliser = normalise) -> IngestResult

# cashapp/pollers/intake/poller.py
@dataclass(frozen=True, slots=True)
class CycleStats: ingested: int; duplicates: int; failed: int; source_errors: int
class IntakePoller: ...  (signature above)

# cashapp/pollers/intake/hooks.py
class CycleHook(Protocol): async def on_cycle(self, container: Container, now: datetime) -> None: ...
CYCLE_HOOKS: list[CycleHook]
async def run_cycle_hooks(hooks: Sequence[CycleHook], container: Container, now: datetime) -> None

# cashapp/pollers/intake/__init__.py
def build(container: Container) -> IntakePoller
    # IntakePoller(container=container, sources=build_sources(container.settings),
    #              object_store=container.resolve(ObjectStore))
ROLE = RoleSpec("intake-poller", "poller", build)

# cashapp/data/models/artifacts.py
class ArtifactPart(Base):   # __tablename__ = "artifact_part"
    id: Mapped[int]                       # identity PK  PK_ARTIFACT_PART
    work_item_id: Mapped[int]             # FK work_item.id  FK_ARTIFACT_PART_ITEM, not null
    part_no: Mapped[int]                  # 1-based; UQ_ARTIFACT_PART_ITEM_NO (work_item_id, part_no)
    kind: Mapped[PartKind]                # StrEnumType(PartKind) VARCHAR2(40): TEXT|PDF|IMAGE|TABLE|DOCX
    media_type: Mapped[str]               # String(255)
    object_key: Mapped[str]               # String(1000)
    source_path: Mapped[str | None]       # String(1000), e.g. "message.eml/attachments/2/inv.pdf"
    size_bytes: Mapped[int]               # BigInteger
    text_preview_chars: Mapped[int | None]  # len(text) when a text object exists, else None
    purged_at: Mapped[datetime | None]    # UtcDateTime; set by s45

# cashapp/data/repositories/artifacts.py
class ArtifactPartRepository(BaseRepository[ArtifactPart]):
    async def for_item(self, work_item_id: int) -> list[ArtifactPart]               # ordered by part_no
    async def for_items(self, work_item_ids: Sequence[int]) -> dict[int, list[ArtifactPart]]
    async def mark_purged(self, parts: Sequence[ArtifactPart], *, at: datetime) -> None   # s45
def is_unique_violation(exc: BaseException) -> bool   # IntegrityError / ORA-00001 / sqlite UNIQUE

# cashapp/services/artifact_parts.py
@dataclass(frozen=True, slots=True)
class LoadedPart: part_no: int; kind: PartKind; media_type: str; data: bytes; text: str | None; source_path: str | None
class ArtifactPurged(Exception): work_item_id: int
async def load_item_parts(uow: UnitOfWork, object_store: ObjectStore, work_item_id: int) -> list[LoadedPart]
    # reads ARTIFACT_PART rows, fetches data (and the .txt object when text_preview_chars), concurrently;
    # TEXT parts: text = data.decode("utf-8"); raises ArtifactPurged if any part has purged_at
```

Consumers: s07/s08 (`load_item_parts`, `ObjectStore`), s17 (`ObjectStore.get(item.artifact_key)`), s30 (`build_object_store`, `ROLE`), s35 (`ingest`, `ArtifactSource`, `FolderSource`, `MailboxSource`), s41/s45 (`CycleHook`, `CYCLE_HOOKS`; s45 also `ArtifactPartRepository.mark_purged`, `ObjectStore.delete`, keys), s34 (fixtures).

### Test fixtures (`api/tests/fixtures/artifacts/`, synthetic, no real names; payer "Example Payer Co", invoices `INV-10001…`)

`build_fixtures.py` (deterministic; run once by the coder, outputs committed): `remittance_body.eml` (plain body with invoice table), `remittance_html.eml` (HTML table body), `body_plus_two_pdfs.eml` (body remittance + 2 PDF remittances: s34 AC4 / s06 3-children case), `forwarded_nested.eml` (attached `.eml`), `newsletter.eml` (non-remittance), `remittance_text.pdf` (hand-written PDF with a text layer), `remittance_scan.pdf` (image-only, Pillow), `encrypted.pdf` (pypdf `encrypt`), `remittance.png`, `remittance.jpg`, `remittance_multipage.tiff`, `remittance.gif`, `remittance.xlsx` (2 sheets, openpyxl), `remittance.csv`, `remittance.docx` (python-docx, text + table), `bundle.zip` (pdf + csv), `nested.zip` (zip in zip, depth 2), `too_deep.zip` (depth 4), `password.zip` (encryption flag bit set by byte patch), `unknown.bin`, `program.exe` (`MZ` header bytes), `remittance.msg` (see Risks).

## Migrations

- One revision `api/alembic/versions/s06_artifact_part.py`, `revision = "s06_artifact_part"`. **Expected parent: the head when it merges** (written against s28's `<rev>_s28_config_tables`); the merger re-points `down_revision` and checks `alembic heads` returns one head.
- Hand-written: `create_table("artifact_part", …)` with the columns above, `PK_ARTIFACT_PART`, `FK_ARTIFACT_PART_ITEM` → `work_item.id`, `UQ_ARTIFACT_PART_ITEM_NO (work_item_id, part_no)` (also serves the FK lookup, so no separate index). `downgrade()` drops the table.
- DEV ATP only.

## TEST PLAN (written and run in step 5 only)

| AC | Test (file::name) |
|---|---|
| 1 | `api/tests/unit/integrations/test_object_store.py::test_local_put_get_exists_delete_roundtrip` |
| 1 | `…::test_local_put_returns_ref_with_size_and_sha256` |
| 1 | `…::test_get_missing_raises_object_not_found` |
| 1 | `…::test_delete_is_idempotent` |
| 1 | `…::test_invalid_or_escaping_key_rejected` (parametrized: `../x`, `/abs`, `artifacts/zz/original`, `artifacts/<hex>/parts/0`) |
| 1 | `…::test_key_builders_match_layout` (`artifacts/{sha}/original`, `…/parts/{n}`, `…/parts/{n}.txt`) |
| 1 | `…::test_oci_store_calls_sdk_with_namespace_bucket_and_metadata` (fake `ObjectStorageClientLike`, asserts `put_object`/`get_object`/`delete_object`/`head_object` args, 404 mapping) |
| 1 | `…::test_factory_local_env_builds_local_store_else_oci` (`make_settings`, OCI client constructor monkeypatched) |
| 2 | `api/tests/unit/intake/test_sources.py::test_folder_source_yields_top_level_files_only` (skips dirs, dotfiles, `~$`, symlinks, `processed/`, `failed/`) |
| 2 | `…::test_folder_source_skips_files_still_settling` (FrozenClock) |
| 2 | `…::test_folder_source_sets_content_type_and_received_at` (`.eml` → `message/rfc822`) |
| 2 | `…::test_mark_processed_moves_to_processed_and_failed` |
| 2 | `…::test_mark_processed_name_collision_gets_suffix` |
| 2 | `…::test_mark_processed_rejects_ref_outside_root` (`../x`, `a/b`) |
| 2 | `…::test_oversize_file_moved_to_failed_not_yielded` |
| 2 | `…::test_fake_mailbox_yields_unmarked_rfc822_messages_and_records_outcomes` |
| 2 | `…::test_fake_and_folder_satisfy_protocols` (static `isinstance`-free assignment checked by pyright + runtime attribute check) |
| 3 | `api/tests/unit/data/test_artifact_part_schema.py::test_model_columns_match_story` (exact column set, nullability, `UQ_ARTIFACT_PART_ITEM_NO`, FK) |
| 3 | `…::test_alembic_single_head_includes_s06` (ScriptDirectory, no DB) |
| 3 | `…::test_repository_for_item_ordered_and_mark_purged` |
| 3 | `api/tests/integration/test_artifact_part_migration_atp.py::test_upgrade_downgrade_upgrade_on_dev_atp` (`@pytest.mark.atp`) |
| 4 | `api/tests/integration/intake/test_ingest.py::test_single_pdf_creates_one_classify_item_parts_history_and_event` (outbox row topic stage CLASSIFY, priority 100, no envelope) |
| 4 | `…::test_email_with_body_and_two_pdfs_creates_envelope_and_three_children` (envelope ARCHIVED/INTAKE, 3 children `parent_id` = envelope, 3 events) |
| 4 | `…::test_original_and_parts_stored_before_commit_under_content_keys` |
| 4 | `…::test_duplicate_raw_artifact_records_history_on_existing_and_creates_nothing` |
| 4 | `…::test_document_seen_before_inside_new_email_is_deduped_per_document` |
| 4 | `…::test_all_documents_duplicate_creates_no_envelope` |
| 4 | `…::test_backlog_kwargs_set_source_kind_batch_and_priority` (`BACKLOG`, `batch_id=7`, `priority=10` on item and outbox) |
| 4 | `…::test_failure_inside_transaction_leaves_no_rows` (normaliser stub returns doc; `emit` patched to raise → no items, parts, history or outbox) |
| 4 | `…::test_unique_race_falls_back_to_duplicate` (pre-insert the hash between check and commit via a stub) |
| 4 | `…::test_text_part_written_as_txt_object_and_load_item_parts_roundtrip` (`load_item_parts` returns data + text; purged part → `ArtifactPurged`) |
| 4 | `api/tests/integration/intake/test_poller.py::test_cycle_reads_interval_from_config_each_cycle` (config change between cycles is honoured; FrozenClock + short `stop`) |
| 4 | `…::test_run_ingests_folder_and_mailbox_then_marks_processed` |
| 4 | `…::test_run_exits_promptly_when_stop_set` |
| 5 | `api/tests/integration/intake/test_ingest.py::test_unsupported_artifact_creates_escalated_classify_item` (STATE=ESCALATED, LAST_ERROR_CODE=UNSUPPORTED_ARTIFACT, detail has reason/media_type, original stored, no outbox row) |
| 6 | `api/tests/unit/intake/test_poller_failures.py::test_failure_on_one_artifact_marks_failed_and_continues` |
| 6 | `…::test_fetch_error_in_one_source_does_not_stop_other_sources` (FakeMailboxSource `fail_fetch_with`) |
| 6 | `…::test_second_cycle_over_same_folder_yields_no_new_items` |
| 6 | `…::test_redelivered_file_after_crash_is_deduped` (commit done, move skipped → next cycle adds only a duplicate history row) |
| 7 | `api/tests/unit/intake/test_hooks.py::test_hooks_run_after_each_cycle_with_container_and_now` |
| 7 | `…::test_hook_error_is_logged_and_loop_continues` (caplog; later hooks still run) |
| 7 | `…::test_cycle_hooks_is_module_level_list` |
| 8 | `api/tests/unit/intake/test_role.py::test_role_spec_name_kind_and_build` (fake Container; `build` returns `IntakePoller` with a `FolderSource` on `settings.intake.drop_folder`) |
| 8 | `…::test_state_reports_running_degraded_stopped` |
| all | `api/tests/unit/intake/test_intake_pii.py::test_no_artifact_content_in_logs` (sentinel subject/body/filename text absent from caplog across ingest + a failing cycle) |

Test support used: s02 `uow_factory`, `FrozenClock`; s28 `make_runtime_config`; s27 `make_settings`; s03 outbox topic helper (`topic_for`) for assertions; s34 real `normalise` with these fixtures (stubs only for failure cases).

## Assumptions and deviations

- **Single-document item hash:** `CONTENT_HASH` = the document hash (envelope and unsupported items use the raw hash). Dedupe is checked at both levels, which satisfies AC4's "deduped the same way" and catches the same PDF arriving alone or inside an email.
- **Part keys use the document hash** (`artifacts/{document_hash}/parts/{n}`), so a part key is stable per document; the original uses the raw hash. Both are `artifacts/{sha256}/…` as the AC requires.
- **Extracted text** lives in a sibling object `<part key>.txt` (no text column in AC3); `TEXT_PREVIEW_CHARS` = its length. s07/s08 read parts only through `load_item_parts`.
- **Added beyond the AC** so dependents never edit these files: `load_item_parts`, `ArtifactPartRepository.for_items/mark_purged`, `is_unique_violation`, `CycleStats`, `IngestResult.envelope_id`, `ingest(clock=, normaliser=)`.
- **Envelope stage is `INTAKE`**, state `ARCHIVED` (terminal; never claimed). Child items carry `artifact_key` = the original, so s17 attaches the whole email.
- **Unsupported items emit no event** (ESCALATED waits for a person; requeue goes through s18/s20).
- s35's story writes `ingest(artifact, *, …)`; the pinned signature is AC4's `ingest(uow_factory, object_store, artifact, *, …)`. s35 follows this plan.
- Hook registration: s41/s45 append to `CYCLE_HOOKS` from their own modules, imported by their own role/package `__init__` that s30's discovery loads; this story imports neither.
- Local object store root = `<drop_folder>/.objectstore` (no new setting; FolderSource ignores dot-directories).
- Interval is clamped to ≥ 1 s so a misconfigured 0 cannot hot-loop.
- `StageEvent` construction per the field list in s03's story until s03's plan pins a helper.

## Risks

- **`.msg` fixture:** no MSG writer is in the dependency set. `build_fixtures.py` emits `remittance.msg` only if a hand-built OLE/CFB writer in the script succeeds; otherwise the file is absent and s34's `.msg` test skips with a reason. Flagged to s34.
- **Orphan objects:** parts are stored before the DB transaction; a failed commit leaves content-addressed objects with no row. They are overwritten on retry and harmless; s45 purges by row, so true orphans are not reclaimed (acceptable; logged).
- **OCI SDK shape** (`opc_meta`, `head_object` 404) is from SDK knowledge: **VERIFY** with a `-m live` probe against a DEV bucket before release.
- **Mounted drop folder semantics** (SMB/NFS rename across directories, mtime granularity): the settle window and same-volume `processed/`/`failed/` subfolders keep moves atomic; verify on the real mount.
- s34 is same-wave: if `NormalisationResult` or `PartKind` names drift, the coder adapts imports only; the ingest flow is unchanged.
- The status/constant layering test in s02 scans string constants; history reasoning strings here ("envelope", "duplicate received from …") are not status values, so no clash.
