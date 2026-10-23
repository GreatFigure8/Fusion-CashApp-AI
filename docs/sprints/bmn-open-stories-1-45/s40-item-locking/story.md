# s40-item-locking: Item locking for human work

- Issue: #40
- Wave: 2 (owns `cashapp/services/locking.py`, `cashapp/api/routers/locks.py`, `cashapp/data/repositories/locks.py`)
- breaking: false

## Story

As a person working an item, I want automation unable to touch it until I requeue or release it, with abandoned locks expiring, so that the system never acts behind me.

## Context

Lock columns are on `WORK_ITEM` (s02): LOCK_OWNER, LOCK_OWNER_NAME, LOCK_ACQUIRED_AT, LOCK_EXPIRES_AT. This story is the only writer of them. StageRunner's claim (s03) already skips live locks. An expired lock (`LOCK_EXPIRES_AT <= now`) is treated as free everywhere (lazy expiry; no sweeper).

## Acceptance criteria

1. [unit] `LockService` (`cashapp/services/locking.py`): `acquire(uow, item_id, principal) -> LockInfo` (lease = `locks.lease_minutes`), `renew(uow, item_id, principal) -> LockInfo`, `release(uow, item_id, principal) -> None`, `force_take(uow, item_id, principal, reason) -> LockInfo`, `is_locked_for_automation(item, now) -> bool`, `assert_held_by(item, principal, now)`. `LockInfo{item_id, owner, owner_name, acquired_at, expires_at}`.
2. [unit] `acquire` fails with `LockConflict(owner_name, acquired_at)` when another person holds a live lock, and with `ItemBusy` when the item is `IN_PROGRESS` with a live claim; acquiring your own live lock renews it. `renew`/`release` by a non-owner fail with `LockNotHeld`.
3. [unit] Every acquire/renew-after-expiry/release/force-take writes a history row (ACTION=LOCK, actor, reason for force-take) via `record_history`; force-take requires permission `items:work` and a non-empty reason and records the previous owner.
4. [api] `POST /items/{id}/lock` (items:work) → 200 LockInfo | 409 `{code:"lock_conflict", details:[{owner_name, acquired_at}]}` | 409 `{code:"item_busy"}`; `POST /items/{id}/lock/renew` → 200 | 409 `lock_not_held`; `DELETE /items/{id}/lock` → 204; `POST /items/{id}/lock/force` body `{reason}` → 200; `GET /items/{id}/lock` → `LockInfo | null` (items:read).
5. [integration] Every station and auto-fix handler respects locks: a test locks an item, publishes its `StageEvent`, and asserts the runner skips it (no state change); after expiry the same event is processed. s18's handlers call `is_locked_for_automation` before acting (asserted in s18).
6. [unit] Lock state is exposed for display: `LockInfo` is included by s19's item/flow APIs via `lock_info_for(item) -> LockInfo | None` from this service (live locks only).

## Out of scope

Workbench UI (s20); lock display in the flow monitor (s19).

## Deps

- s02-data-layer-foundation — WORK_ITEM lock columns, `record_history`, `Clock`. plannable.
- s04-sign-in-authorization — `Principal`, `require_permission`. plannable.
- s28-runtime-config-service — `RuntimeConfig.locks().lease_minutes`. plannable.
- s03-pipeline-runtime — claim query excludes live locks (AC5 test drives `run_stage_once`). plannable (same wave).

## Lifecycle

States of a lock: none → held(owner, expires_at) via acquire/force_take; held → held via renew; held → none via release, via s18 requeue (which calls `release` in the same transaction), or lazily by expiry. Consumers holding the object open: s20's detail sheet (has ACs for expiry, force-take by another, release by requeue).

## Assumptions

- Default lease 30 minutes; UI renews while the sheet is open.
