# s45-data-retention-purge: Data retention and purge

- Issue: #45
- Wave: 4 (owns `cashapp/services/retention/`, `cashapp/api/routers/retention.py`; appends one hook to `cashapp/pollers/intake/hooks.py`)
- breaking: false

## Story

As the data owner, I want raw artifacts and model outputs containing client data kept only as long as policy allows, while the decision audit trail survives, so that we hold the minimum client data without losing "why did the system do this?".

## Context

Retention periods are configuration (`retention.raw_artifact_days`, `retention.extraction_days`, `retention.history_payload_days`; default null = keep, because the periods are an open business decision). No scheduler: triggered on demand or by the intake poller's cycle hook (s06).

## Acceptance criteria

1. [unit] `RetentionService.purge(uow_factory, object_store, now, *, dry_run=False, limit=500) -> PurgeReport{artifacts, parts, readings, adjudications, history_payloads}` only touches items in a terminal state (DONE or ARCHIVED) whose `UPDATED_AT` is older than the relevant period; nothing happens for a null period (test).
2. [integration] Raw artifacts: deletes `artifacts/{hash}/original` and parts from Object Storage, sets `ARTIFACT_PART.PURGED_AT`, and records a tombstone history row (ACTION=DECISION, "artifact purged under retention policy", hash, sizes) — `CONTENT_HASH` stays so dedupe still works.
3. [integration] Extraction payloads: nulls `EXTRACTION_READING.OUTPUT`, `ADJUDICATION.FINAL/DISAGREEMENTS`, sets `PURGED_AT`, keeps `PROVENANCE`, confidence, model/prompt/schema versions and the item's summary columns (amount, currency, dates, customer) so the decision trail remains.
4. [integration] History payloads: nulls `WORK_ITEM_HISTORY.PAYLOAD` and sets `PURGED_AT`, keeping action, actor, stages, states, error codes and reasoning.
5. [unit] Purge runs in bounded batches, each in its own transaction (Object Storage deletes after the DB commit is recorded as pending, then confirmed; a crash leaves re-purgeable rows, never a DB row pointing to a deleted object without a tombstone).
6. [api] `POST /admin/retention/purge` (`config:write`) body `{dry_run: bool}` → `PurgeReport`; recorded in history/config audit with the principal.
7. [unit] A `RetentionCycleHook` appended to `CYCLE_HOOKS` (s06) runs `purge(limit=100)` at most once per hour (tracked in `CONFIG_SETTING`-backed marker or in-memory per process) on the intake poller's cycle.

## Out of scope

Deciding the periods (business); the configuration UI (s21 shows the keys).

## Deps

- s06-intake-poller — `CycleHook` Protocol, `CYCLE_HOOKS`, `ObjectStore.delete`, `ARTIFACT_PART`. plannable.
- s08-extraction-fan-out — `EXTRACTION_READING` columns. plannable.
- s09-adjudicate-fan-in — `ADJUDICATION` columns. plannable.
- s28-runtime-config-service — `config.retention()`, `ConfigAudit`. plannable.
- s04-sign-in-authorization — `require_permission(CONFIG_WRITE)`. plannable.

## Assumptions

- Only terminal items are purged; items still being worked keep their data regardless of age.
