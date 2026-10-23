# s17-fusion-write-back: plan

Issue #17. Wave 5 (money path). Python only: no web files, no UI (s20 shows the FUSION_WRITE history rows this story writes). Paths: `cashapp/` = `api/src/cashapp/`. No LLM: the note is a code template (story assumption), so no Haiku call and no `claude-api` surface.

## Standards followed

- **CLAUDE.md, Write-back.** The receipt note says what was applied and why lines failed; the remittance is attached to the receipt. The note field is small, so the note is a counted, truncating template.
- **CLAUDE.md, Fusion integration.** Every Fusion call goes through s05's `FusionClient` (`get_receipt`, `attach_to_receipt`, `set_receipt_comment`, plus the one read added here, `list_receipt_attachments`). Never guess a field: every name stays an `# UNVERIFIED:` constant in `integrations/fusion/` with a `CONTRACTS.md` row until the `-m live` probe confirms it. Writes stay behind s05's `WriteGuard` (`fusion.write_enabled`, prod-pod refusal); this story adds no second guard.
- **Reference doc §1.** "Tell the story in Fusion"; attach the remittance even when the receipt is already fully applied (s16 calls the same `write_back` with `mode="already_applied"`, so write-back exists once).
- **Layering (CLAUDE.md, `python-web-app:building-python-web-apps`).** `services/receipt_note.py` is pure (no I/O). `services/write_back.py` takes the client and store as plain arguments (`WriteBackDeps`) and never touches `Request`. Only repositories touch the ORM; this story adds no repository and no query outside one (it reads through s02's `HistoryRepository.for_item` and s15's `LineResultRepository.for_item` / `ApplicationLedgerRepository.for_item`).
- **DRY (non-negotiable 7).** One `StageRunner` subclass; statuses (`LineStatus`, `APPLIED_LINE_STATUSES`), `ErrorCode.WRITE_BACK_FAILED`, `HistoryAction.FUSION_WRITE`, `to_money` are imported from s02. History only through `record_history`. Role built with s03's `consumer_role`.
- **A write-back failure never undoes applications.** No code path in this story writes `APPLICATION_LEDGER` or `LINE_RESULT`; the runner test asserts both tables are byte-identical before and after a failing run.
- **Transactions (s03 rule).** Stations may `ctx.uow.commit()` mid-process to persist work as it happens. `write_back` commits one FUSION_WRITE history row immediately after each successful Fusion write, so a later failure (rollback of the outcome UoW) never loses the record of what Fusion already holds. The transition is the runner's last commit.
- **PII (CLAUDE.md conventions, s29).** The note contains only the item id, date, counts, currency, amounts and transaction numbers; never payer names, email subjects, senders, or source filenames. The attachment filename is `remittance-WI-<id>.<ext>` (only the suffix of the original name is kept, whitelisted). Logs carry ids, codes and counts only.
- **Auditability.** Every Fusion write is a FUSION_WRITE history row with op, receipt id, attachment id/filename, mode and the note text written.
- **research.md.** Built and tested against `FakeFusionClient` and `LocalFolderObjectStore`; the fake is never presented as a confirmed contract.

## Pre-check done while planning (read-only)

`aix-greenlight` `fusion_rest_describe` on `standardReceipts` (a non-production pod, 2026-10-23, metadata only, no write):
- `Comments`: string, `maxLength` 2000, updatable. (`ReversalComments` is 240 and not updatable; not used.)
- child `attachments`: `DatatypeCode` (mandatory), `FileName`, `Title`, `UploadedFileContentType`, `FileContents` (attachment), `AttachedDocumentId`, `CreationDate`.

This matches s05's pinned PATCH/POST shapes. It is metadata on one pod, not a write probe, so the code paths stay UNVERIFIED and the default `fusion.receipt_note_max_chars` stays at the story's conservative 240 (a person reading the receipt screen sees the whole note). The coder records the describe result in `CONTRACTS.md` as "describe-confirmed, write UNVERIFIED".

## Files to touch

| Path | New/Edit | Content |
|---|---|---|
| `cashapp/services/receipt_note.py` | new | `NoteItem`, `NoteLine` Protocols, `SHORT_REASONS`, `NOTE_PREFIX`, `NOTE_SEPARATOR`, `PRIOR_NOTE_MARKER`, `compose_receipt_note`, `note_segment`, `merge_note` |
| `cashapp/services/write_back.py` | new | `WriteBackMode`, `WriteBackDeps`, `WriteBackResult`, `write_back`, `attachment_name`, `receipts_for_write_back` |
| `cashapp/stations/write_back/__init__.py` | new | `from .runner import ROLE` |
| `cashapp/stations/write_back/runner.py` | new | `WriteBackRunner(StageRunner)`, `build`, `ROLE` |
| `cashapp/domain/config_keys.py` | edit (append only) | `FUSION_RECEIPT_NOTE_MAX_CHARS` (`fusion.receipt_note_max_chars`, `Annotated[int, Field(ge=60, le=2000)]`, default 240, group `fusion`) |
| `cashapp/integrations/fusion/client.py` | edit (s05) | `list_receipt_attachments` on the `FusionClient` Protocol and `HttpFusionClient` (`# UNVERIFIED:`) |
| `cashapp/integrations/fusion/models.py` | edit (s05) | `AttachmentRef.title: str \| None = None` (appended, defaulted; existing constructors unchanged) |
| `cashapp/integrations/fusion/query.py` | edit (s05) | `FIELDS_ATTACHMENTS = "AttachedDocumentId,FileName,Title,CreationDate"` |
| `cashapp/integrations/fusion/fake.py` | edit (s05) | `list_receipt_attachments` returns `attachments(receipt_id)` (records a `FakeCall`; a read, so no guard) |
| `cashapp/integrations/fusion/CONTRACTS.md` | edit (s05) | rows for `Comments` (describe: 2000, updatable), attachments child fields, `list_receipt_attachments` GET; status per the probe |
| `api/tests/unit/services/test_receipt_note.py` | new | step 5 |
| `api/tests/unit/services/test_write_back.py` | new | step 5 |
| `api/tests/unit/stations/test_write_back_role.py` | new | step 5 |
| `api/tests/integration/stations/test_write_back_runner.py` | new | step 5 |
| `api/tests/unit/fusion/test_fusion_attachments_list.py` | new | step 5 (respx for the new GET; fake behaviour) |
| `api/tests/live/fusion/test_fusion_write_back_live.py` | new | step 5, `@pytest.mark.live` |

Not touched: `main.py`, lockfiles, `status.py`, `error_codes.py` (`WRITE_BACK_FAILED` and `FUSION_WRITE_DISABLED` exist in s02), s15's models/repositories (consumed only), s16's runner, s05's `test_fusion_live.py` (this story's probes live in their own file), `cashapp/stations/__init__.py` / `cashapp/services/__init__.py` (create empty only if absent). No Alembic revision.

The s05 edits are additive (one Protocol method, one defaulted field, one constant, one fake method) and are the only overlap with another story's files; s39 also adds a method to the same Protocol, so the merger takes both.

## Design

### Note composition (`services/receipt_note.py`, pure)

```
NOTE_PREFIX = "CashApp WI-{id} {date}:"         # date = on.isoformat()
NOTE_SEPARATOR = " | "
PRIOR_NOTE_MARKER = "[earlier note replaced]"
```

`note_segment(item, line_results, *, mode, on, max_chars) -> str`:
- `mode="applied"`: `applied` = lines with `line_status in APPLIED_LINE_STATUSES`; `n` = all lines; total = `to_money(sum(applied_amount))` formatted `f"{x:,.2f}"`, currency `item.currency or "?"`.
  `CashApp WI-20481 2026-10-23: applied 5/7 (USD 12,480.00).`
  then ` Prev applied 1.` when any line is `ALLOCATION_PREVIOUSLY_APPLIED`,
  then ` Failed: INV-1044 not found; INV-1050 no balance.` for every other line in `line_no` order,
  then ` See app.`
- `mode="already_applied"`: `CashApp WI-20481 2026-10-23: remittance received; 3 invoice(s) already applied. See app.` (n = previously-applied lines, else all lines).
- `SHORT_REASONS: Mapping[LineStatus, str]`: invoice-not-found → "not found"; customer-not-found → "no customer"; no-remaining-balance → "no balance"; zero-amount → "zero amount"; missing-payment-date → "no date"; no-receipt-match → "no receipt"; apply-failed → "apply failed"; dry-run → "dry run"; anything else → the status value. A failed line with no transaction number shows `line <n>`.
- Transaction numbers are stripped of control characters and capped at 30 chars.
- **Truncation:** the header (counts) and ` See app.` are always kept. Failed entries are added one by one while the segment, plus a reserved ` …+N more` tail, fits `max_chars`; omitted entries become `…+N more`. If even header + ` See app.` exceeds `max_chars`, the header is cut to `max_chars - 1` + `…`. `len(result) <= max_chars` always.

`merge_note(existing, segment, *, work_item_id, max_chars) -> str`:
1. Split `existing` on `NOTE_SEPARATOR`; drop segments that start with `f"CashApp WI-{work_item_id} "` (a re-run replaces its own earlier segment, never duplicates it) and a bare `PRIOR_NOTE_MARKER`.
2. Kept text empty → `segment`.
3. `kept + SEP + segment` fits → that (previous text kept, ours appended).
4. Else `PRIOR_NOTE_MARKER + SEP + segment` if it fits, else `segment`.

`compose_receipt_note(item, line_results, max_chars, *, existing=None, mode="applied", on) -> str` = `merge_note(existing, note_segment(...), ...)`. The segment is composed with `max_chars - len(PRIOR_NOTE_MARKER + SEP)` headroom only when it would otherwise not fit alongside the marker; it never exceeds `max_chars`.

### `write_back` (`services/write_back.py`)

```
async def write_back(uow, item, receipt_id, *, mode, deps, note_max_chars, clock) -> WriteBackResult
```
1. **Lines:** `uow.repo(LineResultRepository).for_item(item.id)` (s16 must have upserted its `allocation-previously-applied` rows in the same UoW, flushed, before calling).
2. **Attachment** (step `attach`):
   - `filename, content_type = attachment_name(item)`: `.eml` / `message/rfc822` for `SourceKind.MAILBOX`; otherwise the suffix of `source_ref` if it matches `^\.[a-z0-9]{1,8}$` (lower-cased) with `mimetypes.guess_type`, else `.bin` / `application/octet-stream`. Title = `remittance-WI-<id>` (filename without extension).
   - Artifact key: `item.artifact_key`, else the parent item's `artifact_key` (children created by normalisation).
   - **Idempotency, two guards:** (a) a FUSION_WRITE history row for this item with `payload.op == "attach"`, same `receipt_id` and `filename` → reuse its `attachment_ref`; (b) otherwise `deps.fusion.list_receipt_attachments(receipt_id)` has an entry whose `filename` or `title` equals ours → reuse it (covers an attach whose history commit was lost or an `outcome_unknown` timeout). Only when both miss: `object_store.get(key)` then `attach_to_receipt(receipt_id, filename, content, content_type, title)`.
   - `ObjectNotFound` (artifact purged by s45 or never stored): the attachment is skipped, not failed (a retry cannot fix it); `attachment_ref=None`, `attachment_skipped="artifact_unavailable"` in the history payload. Other object-store errors → failure with cause `OBJECT_STORE_ERROR`, retryable.
   - Success → `record_history(FUSION_WRITE, payload={"op":"attach","mode","receipt_id","attachment_id","filename","title","reused": bool})` and `await uow.commit()`.
3. **Note** (step `note`): `existing = (await deps.fusion.get_receipt(receipt_id)).comments`; `text = compose_receipt_note(...)`. Equal to `existing` → no PATCH (`note_already_present=True`). Else `set_receipt_comment(receipt_id, text)` → FUSION_WRITE history row `{"op":"note","mode","receipt_id","chars":len(text),"note":text,"previous_note":existing}` and commit.
4. Both steps are attempted even when the first fails (the note is still worth writing if the attach faults, and vice versa). Failures are collected; if any, raise
   `StageError(WRITE_BACK_FAILED, detail={"cause": <first cause>, "step": "attach"|"note", "retryable": bool, "fusion_code": str|None, "http_status": int|None, "outcome_unknown": bool, "failures": [{"step","cause","retryable"}...]})`.
   `cause` is `FusionError.code.value` (so `fusion.write_enabled=false` gives `cause="FUSION_WRITE_DISABLED"`, `retryable=False`, raised by s05's guard before any I/O), or `OBJECT_STORE_ERROR`. Messages and bodies never go into `detail`.
5. Returns `WriteBackResult`.

`receipts_for_write_back(uow, item_id) -> list[int]`: the `receipt_id` in the payload of the latest STAGE_TRANSITION history row with `to_stage=WRITE_BACK` (request to s15: `Advance(WRITE_BACK, payload={"receipt_id": ...})`, mirroring s13's `Advance(MATCH_LINES, payload={receipt_id})`), unioned with the distinct `RECEIPT_ID`s of `ApplicationLedgerRepository.for_item(item_id)`; sorted, de-duplicated.

### `WriteBackRunner` (stage `WRITE_BACK`)

```
class WriteBackRunner(StageRunner):
    stage = Stage.WRITE_BACK
    def __init__(self, deps: RunnerDeps, *, write_back_deps: WriteBackDeps) -> None
    @classmethod
    def build(cls, c: Container) -> Self   # WriteBackDeps(fusion=c.resolve(FusionClient), object_store=c.resolve(ObjectStore))
    async def process(self, ctx) -> StageOutcome
```
1. `item.payment_status is None` → `StageError(WRITE_BACK_FAILED, {"cause": "PAYMENT_STATUS_MISSING", "retryable": False})` (s15 invariant broken; a person looks).
2. `receipts = receipts_for_write_back(...)`. Empty → DECISION history row "no receipt to write back to; nothing written in Fusion" and `Finish(item.payment_status)` (nothing to attach to; never blocks closing).
3. For each receipt: `write_back(ctx.uow, item, rid, mode="applied", deps, note_max_chars=ctx.config.get(FUSION_RECEIPT_NOTE_MAX_CHARS), clock=ctx.clock)`. `StageError` propagates unchanged (s03 rolls back only uncommitted work; FUSION_WRITE rows already committed stay).
4. `Finish(item.payment_status, note="write-back done: attachment <id|reused|skipped>, note <written|present>")` → s03 sets STAGE=DONE, STATE=DONE.

`ROLE = consumer_role(WriteBackRunner, "write-back")` (a `RoleSpec("write-back", "consumer", build)`).

Retry of transient causes: s18's `WRITE_BACK_FAILED` handler returns `Retry(backoff)` when `detail["retryable"]` and attempts < `retries.max_attempts_for(WRITE_BACK_FAILED)`, else `Escalate`. A rerun is safe through the idempotency guards above. (Contract for s18; see Risks.)

## Interfaces provided (pinned)

```python
# cashapp/services/receipt_note.py
NOTE_PREFIX: Final = "CashApp WI-{id} {date}:"
NOTE_SEPARATOR: Final = " | "
PRIOR_NOTE_MARKER: Final = "[earlier note replaced]"
SHORT_REASONS: Mapping[LineStatus, str]
WriteBackMode = Literal["applied", "already_applied"]

class NoteItem(Protocol):            # WorkItem satisfies it
    @property
    def id(self) -> int: ...
    @property
    def currency(self) -> str | None: ...

class NoteLine(Protocol):            # s15's LineResult row satisfies it
    @property
    def line_no(self) -> int: ...
    @property
    def transaction_number(self) -> str | None: ...
    @property
    def line_status(self) -> LineStatus: ...
    @property
    def applied_amount(self) -> Decimal | None: ...

def note_segment(item: NoteItem, line_results: Sequence[NoteLine], *, mode: WriteBackMode,
                 on: date, max_chars: int) -> str
def merge_note(existing: str | None, segment: str, *, work_item_id: int, max_chars: int) -> str
def compose_receipt_note(item: NoteItem, line_results: Sequence[NoteLine], max_chars: int, *,
                         existing: str | None = None, mode: WriteBackMode = "applied",
                         on: date) -> str               # len(result) <= max_chars

# cashapp/services/write_back.py
@dataclass(frozen=True, slots=True)
class WriteBackDeps:
    fusion: FusionClient
    object_store: ObjectStore
    @classmethod
    def from_container(cls, c: Container) -> WriteBackDeps

@dataclass(frozen=True, slots=True)
class WriteBackResult:
    note_written: bool                     # a PATCH was sent this call
    attachment_ref: AttachmentRef | None   # None only when the artifact is unavailable
    note_already_present: bool = False
    attachment_reused: bool = False

def attachment_name(item: WorkItem) -> tuple[str, str]   # (filename, content_type)
async def receipts_for_write_back(uow: UnitOfWork, item_id: int) -> list[int]
async def write_back(uow: UnitOfWork, item: WorkItem, receipt_id: int, *, mode: WriteBackMode,
                     deps: WriteBackDeps, note_max_chars: int, clock: Clock) -> WriteBackResult
    # commits after each successful Fusion write; raises StageError(WRITE_BACK_FAILED, detail) — detail keys:
    # cause (ErrorCode value | "OBJECT_STORE_ERROR" | "PAYMENT_STATUS_MISSING"), step, retryable,
    # fusion_code, http_status, outcome_unknown, failures[]
    # Never writes APPLICATION_LEDGER or LINE_RESULT.

# cashapp/stations/write_back/runner.py
class WriteBackRunner(StageRunner): stage = Stage.WRITE_BACK
ROLE: RoleSpec                                     # name "write-back", kind "consumer"

# cashapp/domain/config_keys.py (appended)
FUSION_RECEIPT_NOTE_MAX_CHARS: ConfigKey[int]      # "fusion.receipt_note_max_chars", 60..2000, default 240

# cashapp/integrations/fusion/client.py (added to the s05 Protocol, HttpFusionClient and FakeFusionClient)
async def list_receipt_attachments(self, receipt_id: int) -> list[AttachmentRef]: ...
    # UNVERIFIED: GET standardReceipts/{id}/child/attachments, fields=FIELDS_ATTACHMENTS, hasMore paging
# cashapp/integrations/fusion/models.py
class AttachmentRef: receipt_id: int; attachment_id: str | None; filename: str; title: str | None = None
```

History payload contract (for s19/s20/s41): `action=FUSION_WRITE`, `payload.op in {"attach","note"}`, plus the keys listed under Design.

Requests to other stories (no code here):
- **s15:** `Advance(WRITE_BACK, payload={"receipt_id": <id>})`; `PAYMENT_STATUS` set before advancing (already in s15 AC6).
- **s16:** call `write_back(..., mode="already_applied", deps=WriteBackDeps.from_container(c), note_max_chars=ctx.config.get(FUSION_RECEIPT_NOTE_MAX_CHARS), clock=ctx.clock)` after upserting its `LINE_RESULT` rows; let `StageError(WRITE_BACK_FAILED)` propagate.
- **s18:** `WRITE_BACK_FAILED` handler retries when `detail["retryable"]` within the limit, then escalates.

## Migrations

None. No table or column is added; idempotency uses `WORK_ITEM_HISTORY` (s02) and Fusion's attachment list. The Alembic head is unchanged (expected parent: whatever head s15/s16 leave; this story adds no revision). The config key needs no DDL (stored settings are rows in s28's table).

## TEST PLAN (written and run only at step 5)

| AC | Test (file::name) |
|---|---|
| 1 | `api/tests/live/fusion/test_fusion_write_back_live.py::test_live_receipt_comments_field_and_length` (`@pytest.mark.live`; `rest_get("standardReceipts/describe")` on the pod named by `CASHAPP_FUSION_LIVE_POD`, `is_production=False`: `Comments` exists, updatable, `maxLength >= FUSION_RECEIPT_NOTE_MAX_CHARS.default`; calls s05's `record_confirmation`) |
| 1 | `…::test_live_attachment_round_trip_and_comment` (`@pytest.mark.live`, also needs `fusion.write_enabled` and `CASHAPP_FUSION_LIVE_WRITES=1` and an s23-tagged receipt in `CASHAPP_FUSION_LIVE_RECEIPT_ID`: attach a 20-byte `.txt`, `list_receipt_attachments` shows it, `set_receipt_comment` then `get_receipt().comments` equal; records confirmations) |
| 1 | `api/tests/unit/fusion/test_fusion_attachments_list.py::test_list_receipt_attachments_query_and_mapping` (respx: path, `fields=FIELDS_ATTACHMENTS`, RFV 4, `hasMore` paging, maps `AttachedDocumentId`/`FileName`/`Title`) |
| 1 | `…::test_fake_lists_attachments_added_by_attach` |
| 1 | `…::test_new_code_paths_carry_unverified_markers` (`list_receipt_attachments` has an `# UNVERIFIED:` tag with a `CONTRACTS.md` row; s05's marker test also covers it) |
| 1 | `api/tests/unit/services/test_receipt_note.py::test_max_chars_comes_from_config_default_240` (`FUSION_RECEIPT_NOTE_MAX_CHARS.default == 240`, bounds 60..2000 validated) |
| 2 | `test_receipt_note.py::test_applied_note_matches_template` (5/7 applied, USD 12,480.00, two failures → exact string from the story) |
| 2 | `…::test_deterministic_same_input_same_output` |
| 2 | `…::test_truncates_failed_lines_with_more_marker_within_max_chars` (parametrised max_chars 60, 120, 240; always `<= max_chars`, `…+N more` count correct, header kept) |
| 2 | `…::test_header_alone_too_long_is_cut_with_ellipsis` |
| 2 | `…::test_note_never_contains_payer_or_email_text` (item with payer name, subject and sender sentinels; only transaction numbers appear) |
| 2 | `…::test_short_reason_for_every_non_applied_line_status` (iterates `LineStatus`) |
| 2 | `…::test_appends_to_existing_note_when_it_fits` |
| 2 | `…::test_replaces_with_marker_when_existing_too_long` |
| 2 | `…::test_rerun_replaces_own_segment_not_duplicated` |
| 2 | `…::test_already_applied_mode_text` |
| 2 | `…::test_no_llm_dependency` (module imports nothing from `cashapp.integrations.llm`) |
| 3 | `api/tests/unit/services/test_write_back.py::test_attaches_original_artifact_with_named_file` (MAILBOX → `remittance-WI-<id>.eml`, `message/rfc822`, bytes from `LocalFolderObjectStore`; FOLDER `.pdf` → `.pdf`/`application/pdf`; odd suffix → `.bin`) |
| 3 | `…::test_sets_note_via_set_receipt_comment` (fake `comments(receipt_id)` equals composed text) |
| 3 | `…::test_idempotent_on_rerun_via_history` (second call: no new attach, no PATCH; `attachment_reused`, `note_already_present`) |
| 3 | `…::test_idempotent_via_fusion_list_when_history_missing` (attachment pre-seeded in the fake only → no second attach) |
| 3 | `…::test_fusion_write_history_rows_committed_per_write` (rows survive a rollback after a later failure) |
| 3 | `…::test_missing_artifact_skips_attachment_but_writes_note` |
| 3 | `…::test_child_item_uses_parent_artifact_key` |
| 3 | `…::test_receipts_for_write_back_from_payload_and_ledger` |
| 4 | `api/tests/integration/stations/test_write_back_runner.py::test_writes_back_and_finishes_done_with_payment_status` (`run_stage_once`; STATE=DONE, STAGE=DONE, PAYMENT_STATUS unchanged, FUSION_WRITE rows for attach and note) |
| 4 | `…::test_failure_raises_write_back_failed_and_leaves_ledger_and_line_results_unchanged` (`fail_next("set_receipt_comment", FusionError(FUSION_TRANSIENT))`; snapshot of `APPLICATION_LEDGER` and `LINE_RESULT` equal before/after; `LAST_ERROR_CODE=WRITE_BACK_FAILED`, `detail.retryable=True`) |
| 4 | `…::test_retry_after_transient_completes_without_duplicate_attachment` (second `run_stage_once` after the failure: one attachment in the fake, DONE) |
| 4 | `…::test_no_receipt_finishes_without_fusion_write` |
| 4 | `…::test_missing_payment_status_is_write_back_failed` |
| 5 | `test_write_back.py::test_write_disabled_raises_write_back_failed_with_cause` (`WriteGuard(write_enabled=False, ...)` in the fake: `StageError.code == WRITE_BACK_FAILED`, `detail["cause"] == "FUSION_WRITE_DISABLED"`, `retryable False`, zero write calls recorded, ledger and line results untouched) |
| 6 | `api/tests/unit/stations/test_write_back_role.py::test_role_spec_name_kind_and_build` (`ROLE.name == "write-back"`, `ROLE.kind == "consumer"`, `build(FakeContainer)` with registered `FakeFusionClient` and `LocalFolderObjectStore` returns a Runnable; discovered by s30's `discover_roles`) |

## Risks

- **Fusion contract unconfirmed for writes.** Describe confirms `Comments` (2000) and the attachments child on one non-production pod; the PATCH, the POST body and `list_receipt_attachments` are still UNVERIFIED until the live probes run with write credentials. All names stay in s05's constants, so a correction is one file.
- **s18 retry contract.** s18's story AC3 says only `retryable` codes get `Retry`, and `WRITE_BACK_FAILED` is not retryable in s02, while this story's AC4 says transient causes are retried by s18. Pinned resolution: s18's `WRITE_BACK_FAILED` handler reads `detail["retryable"]`. If s18 keeps the strict rule, transient write-back failures escalate at once (safe, just less automated). Flagged for the s18 planner and reviewer.
- **Receipt id hand-off.** Depends on s15 adding `payload={"receipt_id"}` to `Advance(WRITE_BACK)`; the ledger fallback covers every item with at least one planned line. An item with no ledger rows and no payload closes without a Fusion note (recorded as a DECISION row).
- **Duplicate attachment on `outcome_unknown`.** If Fusion processed an attach but the response timed out, and the list endpoint also lags, a retry could attach twice. Two guards (history and list) make this unlikely; a duplicate is harmless (same file).
- **s05 file overlap.** Additive edits to `client.py`, `fake.py`, `models.py`, `query.py`, `CONTRACTS.md`; s39 also edits the Protocol. The merger resolves both.
- **History purge (s45).** A purged history payload removes guard (a); guard (b) still applies.
- **Long existing notes from people.** If a person's note fills the field, ours replaces it with the marker. The person's text is lost from Fusion (it was theirs to keep). Mitigation: the previous text is stored in the FUSION_WRITE payload (`previous_note`) so nothing is lost from the audit trail.

## Assumptions / deviations

- `compose_receipt_note` takes keyword-only `existing`, `mode` and `on` beyond the AC's three positional arguments (needed for append-not-overwrite, s16's mode and determinism).
- `write_back` takes `deps`, `note_max_chars` and `clock` as keyword arguments beyond the AC's `(uow, item, receipt_id, *, mode)`; s16 calls it this way.
- A missing artifact skips the attachment instead of failing (a retry can't fix a purged artifact; the note is still written and history records why).
- Default `fusion.receipt_note_max_chars` stays 240 although describe shows 2000, per the AC; an admin can raise it.
- `list_receipt_attachments` is added to s05's `FusionClient` for idempotency (AC3 allows "list call or recorded attachment_ref"; both are used).
- The FUSION_WRITE note payload also stores `previous_note` (the text that was replaced or appended to), so the audit trail keeps it.
