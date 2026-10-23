# s28-runtime-config-service: Runtime configuration service (database-backed, versioned, audited)

- Issue: #28
- Wave: 1 (serialized spine, step 5 of 6)
- breaking: false

## Story

As an admin, I want every business-tunable value in ATP behind one typed service with a full change history, so that stations pick up changes without a restart and every change is auditable.

## Context

Distinct from s27 (deploy-time settings). Keys and defaults are the registry in `cashapp/domain/config_keys.py` (s02). The group-to-role mapping is a dedicated table owned by s04; this service records that mapping's change history in the same change log (see Deps).

## Acceptance criteria

1. [integration] One Alembic revision creates `CONFIG_SETTING` (KEY pk, VALUE JSON, VERSION, UPDATED_AT, UPDATED_BY) and `CONFIG_CHANGE` (ID, KEY, OLD_VALUE JSON, NEW_VALUE JSON, CHANGED_BY, CHANGED_BY_NAME, CHANGED_AT, REASON).
2. [unit] `cashapp/services/config.py`: `RuntimeConfig` with `async get(key: ConfigKey[T]) -> T` (stored value or registry default, validated against the key type) and typed group accessors returning frozen models: `intake()`, `receipt_watcher()`, `matching()` (date_window_days, tolerance_for(currency) -> Decimal, bank_fee_bands, scorer_weights, min_score), `retries()` (max_attempts_for(code), backoff_seconds), `aging()`, `escalation()`, `models()` (reader_a, reader_b, adjudicator, workhorse: `ModelRole{model_id, effort, timeout_s}`), `extraction()`, `concurrency()`, `locks()`, `backlog()`, `retention()`, `budget()`, `notifications()`, `reports()`, `discount()`.
3. [unit] `ConfigWriter.set(uow, key, value, principal, reason, expected_version) -> int` validates the value, rejects a stale `expected_version` (`ConfigConflict`), and writes the new value and a `CONFIG_CHANGE` row (who, when, old, new, reason) in the caller's transaction. `ConfigAudit.record(uow, key, old, new, principal, reason)` is public for s04's group-role changes.
4. [unit] Changes are visible without a restart: `RuntimeConfig` caches values for at most `ttl_seconds` (default 15) and `snapshot()` returns an immutable view used for one event or one poll cycle.
5. [api] `GET /config` (permission `config:read`) returns every key: `{key, group, description, value, default, version, updated_by, updated_at, admin_only_write}`; `GET /config/{key}/history` returns change rows; `PUT /config/{key}` (permission `config:write`) body `{value, reason, expected_version}` → 200 new entry, 409 on version conflict, 422 on invalid value, all in the single error shape.
6. [unit] Writing a model_id containing "fable" is rejected with 422 (zero-retention rule).
7. [api] Group-to-role mapping (table owned by s04): `GET /access/group-roles` (`config:read`) → `{mappings:[{group_name, role}], updated_by, updated_at}`; `PUT /access/group-roles` (`config:write`, body `{mappings:[{group_name, role}], reason}`) replaces the mapping through `GroupRoleRepository.replace_all` and records `ConfigAudit.record(uow, "access.group_role_map", old, new, principal, reason)` in the same transaction; `GET /access/group-roles/history` returns those change rows. Removing the last ADMIN mapping is refused with 422.

## Out of scope

The configuration screen (s21); group-to-role table (s04).

## Deps

- s02-data-layer-foundation — `CONFIG_KEYS`, `ConfigKey[T]`, `UnitOfWork.repo`, `BaseRepository`. plannable.
- s04-sign-in-authorization — `Principal` (from `cashapp/domain/principal.py`), `require_permission(perm: Permission) -> Callable[..., Awaitable[Principal]]` from `cashapp/auth/deps.py`, and `GroupRoleRepository{all(), replace_all(mappings)}` from `cashapp/data/repositories/group_roles.py`. plannable; s04 runs immediately before s28 in the spine.

## Test-support files owned

`api/tests/support/config.py`: `make_runtime_config(overrides: dict[str, Any] = {}) -> RuntimeConfig` (in-memory store), used by every station test.

## Assumptions

- The issue's "typed accessor for group-to-role mapping" is served by s04's `GroupRoleRepository` plus the `/access/group-roles` endpoints here, audited in `CONFIG_CHANGE`. Logged as deviation.
- 15 s cache TTL satisfies "within one poll or event".
