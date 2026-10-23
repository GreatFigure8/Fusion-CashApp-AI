# s18-auto-fix-engine: Auto-fix engine (typed error codes, handlers, bounded attempts, escalation, human requeue)

- Issue: #18
- Wave: 3 (owns `cashapp/services/autofix/`, `cashapp/domain/notifications.py`, `cashapp/api/routers/requeue.py`)
- breaking: false

## Story

As AR, I want stuck items repaired automatically wherever possible and handed to a person only when the fixes run out, so that the automation rate includes fixes.

## Context

CLAUDE.md *Self-healing* table and reference doc §6. Implements s03's `FailureHandler`. Retry only transient failures; never retry not-found/closed without new information. Always a person: prepayments, PO/SO/ERS-only references, dual-currency payers, anything ungrounded. Human requeue goes back through the same StageRunner (no manual path). Haiku (workhorse) writes reasoning and the "why it's stuck" summary.

## Acceptance criteria

1. [unit] `cashapp/services/autofix/engine.py`: `AutoFixEngine(FailureHandler)` with a registry `register(code: ErrorCode, handler: FixHandler)`; `FixHandler` Protocol `async def decide(ctx: FixContext) -> FailureDecision` where `FixContext{uow, item, error: StageError, attempts_for_code: int, config, clock, reasoner}`; `build_failure_handler(container)` (resolved by s30 by import path). A test asserts every `ErrorCode` has a registered handler.
2. [unit] Handlers (one module each under `handlers/`), each bounded by `config.retries().max_attempts_for(code)`:
   - RECEIPT_NOT_YET_AVAILABLE → first time `ParkAwaitingReceipt` (sets `AWAITING_SINCE`); also sets `FIX_HINTS.match_on_creation_date=true`.
   - RECEIPT_AMBIGUOUS → `Reroute(MATCH_RECEIPT)` once with `FIX_HINTS.narrow=true` (s13 narrows with references and dates), then Escalate.
   - AMOUNT_VARIANCE → Escalate (tolerance and bank-fee bands are applied inside s13 already).
   - CUSTOMER_NOT_FOUND / INVOICE_NOT_FOUND / INVALID_INVOICE_NUMBER → once `Reroute(EXTRACT)` with `FIX_HINTS.rerun_readers=["A","B"]`, `effort="high"` (re-extract), then Escalate; never a plain retry.
   - LOW_EXTRACTION_CONFIDENCE → `Reroute(EXTRACT)` with `effort="high"` once, then Escalate.
   - EXTRACTION_FAILED / LLM_REFUSAL → `Reroute(EXTRACT)` with `rerun_readers` = the failed readers, up to the limit, then Escalate.
   - FUSION_OVERAPPLY, FUSION_ALREADY_APPLIED → `Reroute(MATCH_LINES)` (s15 re-plans from fresh balances and existing applications: clamp / reconcile).
   - FUSION_GL_DATE → `Reroute(APPLY)` with `FIX_HINTS.gl_date_floor=<receipt GL date from error detail>`.
   - FUSION_LOCKED, FUSION_TRANSIENT, LLM_TRANSIENT → `Retry(after=backoff_seconds[attempt])`.
   - PREPAYMENT, PO_SO_ERS_ONLY, DUAL_CURRENCY, UNGROUNDED, CUSTOMER_MULTIPLE_ACCOUNTS, AGED_OUT, UNSUPPORTED_ARTIFACT, WRITE_BACK_FAILED (after retries), REVERSAL_FAILED, SYSTEM_DEAD_LETTER, and everything not listed → Escalate.
3. [unit] Only `retryable` codes (from `ErrorSpec`) ever get `Retry`; a test iterates all codes. When attempts for a code reach the limit, the decision is `Escalate`. Items with a live lock are never acted on (handler returns no-op and logs; asserted with `is_locked_for_automation`).
4. [integration] Every decision writes a history row (ACTION=AUTOFIX_ATTEMPT, error code, attempt n/limit, decision, reasoning). Reasoning text for Escalate comes from `Reasoner.summarise(item, error, attempts) -> str` using `llm.workhorse` (Haiku, ≤ 3 sentences, plain language, no PII beyond what the item shows); if the LLM fails, a template summary is used (never blocks escalation). The summary is stored in `WORK_ITEM.ESCALATION_SUMMARY`.
5. [unit] `escalation.py`: `escalate(uow, item, code, summary|None, principal=SYSTEM_PRINCIPAL)` sets STATE=ESCALATED, LAST_ERROR_CODE, summary, history, and emits a `NotifyEvent` (`cashapp/domain/notifications.py`: `{event_id, kind: "item_escalated"|"dlq_growth"|"outage"|"budget_exceeded", severity: info|warning|critical, work_item_id|None, error_code|None, summary, occurred_at}`, topic `{prefix}.{env}.notify`) via the outbox. Used by s14, s38 and s42's sources.
6. [api] `POST /items/{id}/requeue` (permission `items:work`; caller must hold the live lock, else 409 `lock_not_held`) body `{target_stage?: Stage, corrected_extraction?: RemittanceExtraction, customer_number?: str, receipt_id?: int, learn_alias?: bool = true, note: str}`: in ONE transaction saves the corrected extraction via `save_human_correction` (s09) when given, writes `HUMAN_HINTS`, clears `FIX_HINTS`, resets ATTEMPTS, sets STATE=PENDING at `target_stage` (default: VALIDATE when the extraction was corrected, else the stage it failed in), calls `AliasService.learn` when a customer was chosen and `learn_alias`, releases the lock (`LockService.release`), writes a HUMAN_ACTION history row with a field-level diff, and emits the `StageEvent`. The item then runs through the same StageRunner (integration test: a requeued item reaches the next stage via `run_stage_once`).
7. [unit] Policy guards: an extraction whose lines all reference prepayment/on-account (`kind=UNKNOWN` with no transaction numbers and a prepayment marker) → PREPAYMENT; lines whose transaction numbers don't appear in the artifact text (`UNGROUNDED`, checked against the reading's `quote`/source) → Escalate. These checks are exposed as `policy_check(extraction) -> ErrorCode | None` for s10/s13 to call.

## Out of scope

Stations' own fixes (clamp in s15, narrowing in s13); notification delivery (s42); the workbench UI (s20).

## Deps

- s03-pipeline-runtime — `FailureHandler`, `FailureDecision` variants, `StageError`, `emit`. plannable.
- s02-data-layer-foundation — `ErrorCode`/`ErrorSpec`, `FIX_HINTS`/`HUMAN_HINTS`, `record_history`. plannable.
- s28-runtime-config-service — `retries()`, `escalation()`, `models().workhorse`. plannable.
- s08-extraction-fan-out — `LlmClients.workhorse`, `RemittanceExtraction`, `ReplayLlmClient`. plannable.
- s09-adjudicate-fan-in — `save_human_correction(uow, item_id, final, principal)`. plannable (same wave).
- s37-payer-alias-learning — `AliasService.learn(...)`. plannable (same wave).
- s40-item-locking — `LockService.assert_held_by`, `release`, `is_locked_for_automation`. plannable.
- s04-sign-in-authorization — `require_permission(ITEMS_WORK)`, `SYSTEM_PRINCIPAL`. plannable.

## Lifecycle

Moves: any → PENDING (Retry/Reroute/requeue), → AWAITING_RECEIPT (park), → ESCALATED (escalate). Consumers holding the item open: s20's sheet shows each (ACs there).

## Assumptions

- `policy_check` heuristics are a starting point; thresholds may move to config later.
