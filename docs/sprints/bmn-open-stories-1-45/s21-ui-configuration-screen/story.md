# s21-ui-configuration-screen: UI configuration screen

- Issue: #21
- Wave: 5 (owns `web/app/(shell)/config/**`, `web/components/config/`)
- breaking: false

## Story

As an admin, I want to tune the line without a deploy and see every change in history, so that matching, retries, models and access are adjustable safely and auditably.

## Context

Design screen owned here: design.md §6 "Configuration" (`/config`). Backed entirely by existing APIs: s28 (`/config`, `/config/{key}/history`, `PUT /config/{key}`, `/access/group-roles`), s37 (`/aliases`), s45 keys appear as Retention settings. Writes are admin-only (`config:write`); the API enforces it, the UI hides.

## Acceptance criteria

1. [browser] Design §6 layout: vertical tabs Access (group → role) · Polling · Matching (date window, tolerances per currency, bank-fee bands) · Retries & aging · Models · Retention · Payer aliases; each setting row shows label, description, current value input, unit, and "Changed by J. Stevenson 3 days ago" which opens a history `Sheet` (who, when, old → new, reason) from `GET /config/{key}/history`.
2. [browser] Edits stage locally; sticky footer "3 unsaved changes · Discard · Review & save"; Review opens a dialog listing old → new per key and a required Reason; save sends one `PUT /config/{key}` per changed key with `expected_version`; field errors (422) show inline; a 409 shows "This setting was changed by someone else since you opened it. Reload".
3. [browser] Matching tab: tolerances as a table of currency rows (USD ±0.10, EUR ±0.10, INR ±0.49 from defaults) with Add currency; date window and bank-fee bands editable. Polling: intake and receipt-watcher intervals. Retries & aging: max attempts per error code, backoff list, awaiting-receipt aging days, min extraction confidence, fan-in timeout.
4. [browser] Models tab: rows Reader A, Reader B, Adjudicator, Workhorse with model ID select, effort select, timeout; the fixed note "Claude Fable models are not allowed (zero data retention)."; entering a Fable id is rejected client-side (Zod) and server-side (422 shown inline).
5. [browser] Access tab: group → role table editable via `PUT /access/group-roles` with reason; removing the last admin mapping shows the API's 422 message.
6. [browser] Payer aliases tab: table (alias text, maps to customer, learned from WI link, uses, last used) from `GET /aliases`; Retire with confirmation dialog + reason → `POST /aliases/{id}/retire`; retired aliases leave the active list.
7. [browser] Retention tab shows `retention.*` keys (null shown as "Keep indefinitely") and a "Run purge (dry run)" button calling `POST /admin/retention/purge {dry_run:true}` and showing the report.
8. [browser] Non-admin (`config:read` only): values read-only, footer replaced by "Admin role required to edit"; a user without `config:read` gets s19's unauthorized state.
9. [browser] States: loading skeleton per tab; API error via `error-alert`.

## Out of scope

The config APIs themselves (s28, s37, s45).

## Deps

- s28-runtime-config-service — `GET /config`, `GET /config/{key}/history`, `PUT /config/{key}` (409/422 semantics), `GET/PUT /access/group-roles`. plannable.
- s37-payer-alias-learning — `GET /aliases`, `POST /aliases/{id}/retire`. plannable.
- s45-data-retention-purge — `POST /admin/retention/purge` → `PurgeReport`. plannable.
- s19-ui-shell-flow-monitor — shell, `data-table`, `error-alert`, `empty-state`, unauthorized state, dto fixtures. plannable (same wave, merged first).
- s31-typed-web-api-client — `api()`, `apiAction`, `api-mock.ts`. plannable.
- s04-sign-in-authorization — `/me` permissions, session fixture. plannable.

## Assumptions

- Each key saves independently (no multi-key transaction); the review dialog shows per-key results.
