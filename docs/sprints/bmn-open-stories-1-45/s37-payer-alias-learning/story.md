# s37-payer-alias-learning: Payer alias learning from human decisions

- Issue: #37
- Wave: 3 (owns `cashapp/services/aliases.py`, `cashapp/data/repositories/aliases.py`, `cashapp/api/routers/aliases.py`)
- breaking: false

## Story

As AR, I want each human-confirmed payer-to-customer link and receipt match used immediately, so that the next remittance from that payer resolves itself instead of waiting for a next-day mapping load.

## Context

Consulted first by customer resolution (s11) and by the receipt scorer (s13). Learned from s18's human requeue. Reviewed and retired on the configuration screen (s21).

## Acceptance criteria

1. [integration] One Alembic revision creates `PAYER_ALIAS` (ID, PAYER_NAME_NORM, PAYER_BANK_ACCOUNT, REFERENCE_PATTERN, CUSTOMER_ACCOUNT_NUMBER, LEARNED_FROM_ITEM_ID, CREATED_BY, CREATED_BY_NAME, CREATED_AT, USES, LAST_USED_AT, RETIRED_AT, RETIRED_BY, RETIRE_REASON).
2. [unit] `normalise_payer_name(name) -> str` (casefold, strip punctuation and legal suffixes like inc/ltd/llc/pvt/gmbh, collapse spaces).
3. [unit] `AliasService.lookup(payer_name, bank_account, references) -> AliasMatch{customer_numbers, alias_ids}` (implements `AliasLookup`): matches active aliases by bank account (exact), normalised payer name (exact), or reference pattern (anchored regex, validated at write time); increments USES/LAST_USED_AT. When matches point at more than one customer account, `customer_numbers` has all of them — callers must not auto-assign (s11 escalates; asserted by a test here on the returned shape).
4. [unit] `AliasService.learn(uow, *, item_id, payer_name, bank_account, reference_pattern|None, customer_number, principal) -> PayerAlias` stores who/when; learning the same (name, account) → customer again is idempotent; a conflicting alias for the same key with a different customer is stored too (so the payer becomes multi-account and is never auto-assigned) and a history row notes the conflict.
5. [unit] `AliasService.retire(uow, alias_id, principal, reason)`; retired aliases are never matched.
6. [api] `GET /aliases?active=true&q=` (`config:read`) → paged `{id, alias_text, kind: name|bank_account|reference, customer_number, learned_from_item_id, created_by_name, uses, last_used_at, retired_at}`; `POST /aliases/{id}/retire` (`config:write`) body `{reason}` → 200; changes recorded via `ConfigAudit.record(uow, "aliases", ...)`.
7. [unit] The decision trail shows alias use: s11 and s13 add `alias_ids` to their DECISION history rows (asserted in those stories); this story provides `describe_alias(alias) -> str` for that text.

## Out of scope

The configuration screen tab (s21); calling `learn` (s18 calls it on requeue).

## Deps

- s02-data-layer-foundation — `BaseRepository`, `record_history`. plannable.
- s28-runtime-config-service — `ConfigAudit.record`. plannable.
- s04-sign-in-authorization — `Principal`, `require_permission`. plannable.

## Assumptions

- Receipt-match learning (the issue's "receipt match") is captured as a reference-pattern alias plus the payer bank account; s13 reads them as signals.
