# s07-classify-station: Classify station (Haiku decides whether an artifact is remittance advice)

- Issue: #7
- Wave: 3 (owns `cashapp/stations/classify/`, `cashapp/api/routers/classification.py`, `cashapp/data/repositories/classification.py`)
- breaking: false

## Story

As AR, I want every artifact triaged as remittance advice or not, cheaply, before any expensive extraction runs, so that Opus and Cohere only read remittances.

## Context

Workhorse role: `claude-haiku-5-5` (model ID and effort from config `models.workhorse`), structured output, zero data retention. Non-remittances are archived with their reason, never dropped. A person can override.

## Acceptance criteria

1. [unit] `ClassificationDecision` schema `{is_remittance: bool, reason: str (≤300 chars), confidence: float 0-1}`; prompt in `cashapp/stations/classify/prompts.py` with `PROMPT_VERSION`.
2. [integration] One Alembic revision creates `CLASSIFICATION` (ID, WORK_ITEM_ID, IS_REMITTANCE, REASON, CONFIDENCE, MODEL_ID, PROMPT_VERSION, ORIGIN (MODEL|HUMAN), DECIDED_BY, CREATED_AT).
3. [integration] `ClassifyRunner(StageRunner)` (stage CLASSIFY) sends the item's parts (via `ObjectStore`) to `llm.workhorse.parse(..., ClassificationDecision)` with `config.models().workhorse` model/effort/timeout; stores a CLASSIFICATION row; remittance → `Advance(EXTRACT)`; not remittance → `Archive(reason)` (STATE=ARCHIVED, history with reason). Refusal → `StageError(LLM_REFUSAL)`; transient → `StageError(LLM_TRANSIENT)`; malformed output → `StageError(CLASSIFICATION_FAILED)`.
4. [api] `POST /items/{id}/classification/override` (permission `classification:override`) body `{is_remittance: bool, reason: str}`: stores a HUMAN classification row and a history row with the principal; `is_remittance=true` on an ARCHIVED or CLASSIFY-stage item sets STAGE=EXTRACT, STATE=PENDING and emits `StageEvent(EXTRACT)` in the same transaction; `false` archives the item. Refused with 409 `lock_conflict` when another person holds a live lock, 409 `invalid_state` when the item is past EXTRACT.
5. [unit] Model ID and effort are read from `config.models().workhorse` per event (a config change applies to the next event without restart; test).
6. [unit] `ROLE = RoleSpec("classify", "consumer", build)`.

## Out of scope

UI for the override (the workbench s20 calls this endpoint); extraction.

## Deps

- s03-pipeline-runtime — `StageRunner`, `Advance`, `Archive`, `StageError`, `emit`. plannable.
- s08-extraction-fan-out — `LlmClients.workhorse`, `LlmClient.parse`, `ContentPart`, `ReplayLlmClient`. plannable.
- s06-intake-poller — `ObjectStore`, `ARTIFACT_PART`. plannable.
- s40-item-locking — `LockService.is_locked_for_automation(item, now)` / lock check for the override. plannable.
- s04-sign-in-authorization — `require_permission(Permission.CLASSIFICATION_OVERRIDE)`. plannable.
- s28-runtime-config-service — `config.models().workhorse`. plannable.
- s30-worker-host — `RoleSpec`. plannable.

## Assumptions

- Low-confidence "not remittance" decisions are still archived; the workbench's archived filter is where a person finds them.
