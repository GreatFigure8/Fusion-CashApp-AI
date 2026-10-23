# s35-backlog-reprocessing: Backlog reprocessing (push historical remittances through the line safely)

- Issue: #35
- Wave: 5 (money path; owns `cashapp/services/backlog/`, `cashapp/api/routers/backlog.py`, `cashapp/tools/backlog/`; edits s15's apply step for dry-run and s03's relay throttle binding)
- breaking: false

## Story

As AR, I want tens of thousands of historical remittances pushed through the same pipeline, throttled below live traffic, with a dry run first, so that the backlog gets worked without flooding Fusion.

## Context

Same stations and rules as live traffic; no separate code path. The only differences are the item's `BATCH_ID`, `PRIORITY` (backlog 10 < live 100) and, for dry runs, the apply step recording what it would do. Rate limiting is done by the outbox relay's `PublishThrottle` hook (s03) — no new poller. Progress shows on the flow monitor (s19).

## Acceptance criteria

1. [integration] One Alembic revision creates `BACKLOG_BATCH` (ID, NAME unique, SOURCE_KIND (FOLDER|MAILBOX_FOLDER), SOURCE_REF, DRY_RUN, RATE_LIMIT_PER_MIN, STATUS (IMPORTING|RUNNING|PAUSED|DONE|CANCELLED), TOTAL, CREATED_BY, CREATED_AT, FINISHED_AT) and the FK `WORK_ITEM.BATCH_ID → BACKLOG_BATCH.ID`.
2. [unit] `BacklogService.import_batch(uow_factory, source: ArtifactSource, *, name, dry_run, rate_limit, principal) -> BacklogBatch` reuses s06's intake path (`ingest(artifact, *, source_kind=BACKLOG, batch_id, priority=10)` — the function s06's poller uses, made public by this story if needed) so dedupe, normalisation and Object Storage are identical; CLI `uv run python -m cashapp.tools.backlog import --folder PATH --name B-0007 [--dry-run] [--rate 20]` and a mailbox-folder variant through `MailboxSource`.
3. [unit] Dry run: when the item's batch is `DRY_RUN`, the apply step records ledger rows with STATUS=DRY_RUN and `LINE_RESULT` `allocation-dry-run` with the amounts it would apply, makes NO Fusion write call (test with a fake that fails on any write), and write-back is skipped; the item finishes DONE with the derived status for reporting.
4. [unit] `BacklogThrottle(PublishThrottle)`: outbox rows for items with a `BATCH_ID` are admitted at most `RATE_LIMIT_PER_MIN` per batch (token bucket, default `backlog.rate_limit_per_minute`) and only when no live (PRIORITY ≥ 100) rows are waiting; PAUSED batches admit nothing. Live items are never delayed by backlog (test).
5. [api] `POST /backlog/batches` (`backlog:run`) body `{name, folder, dry_run, rate_limit_per_minute}` → 202 batch; `GET /backlog/batches` and `GET /backlog/batches/{id}` → `{id, name, status, dry_run, total, processed, applied, escalated, failed, rate_limit_per_minute, eta_minutes, started_at}` (counts derived from items by state/payment status); `POST /backlog/batches/{id}/pause|resume|cancel`.
6. [unit] Batch progress is visible in the flow monitor: s19 consumes `GET /backlog/batches?status=RUNNING` (contract above).

## Out of scope

The progress bar UI (s19).

## Deps

- s06-intake-poller — `ingest(...)` path, `ArtifactSource`, `FolderSource`, `MailboxSource`. plannable.
- s03-pipeline-runtime — `PublishThrottle` Protocol, `OutboxRelay` throttle injection. plannable.
- s15-line-matching-apply — apply loop and ledger statuses (`DRY_RUN`). plannable.
- s17-fusion-write-back — `WriteBackRunner` skip for dry-run batches. plannable.
- s02-data-layer-foundation — `WORK_ITEM.BATCH_ID`, `PRIORITY`, `LineStatus.ALLOCATION_DRY_RUN`. plannable.
- s04-sign-in-authorization — `require_permission(BACKLOG_RUN)`. plannable.

## Assumptions

- Dry-run items still call Fusion read endpoints (lookups and matching) — read load is throttled by the same rate limit.
