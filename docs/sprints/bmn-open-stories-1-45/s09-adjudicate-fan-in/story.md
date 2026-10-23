# s09-adjudicate-fan-in: Adjudicate fan-in (Opus 5.5 chooses between the two readings per field)

- Issue: #9
- Wave: 3 (owns `cashapp/stations/adjudicate/`, `cashapp/data/repositories/adjudication.py`)
- breaking: false

## Story

As AR, I want a single trusted extraction out of the two readings, with every value traceable to the reader it came from, so that "why did the system think this?" always has an answer.

## Context

Adjudicator = `claude-opus-5-5`, a separate call from Reader A, that ONLY compares the two readers' outputs and decides per field and per line: take A, take B, or combine. It never sees the artifact. The fan-in wait is enforced by s08 (both readers run concurrently under `extraction.fanin_timeout_seconds`); this station starts once both readings are terminal.

## Acceptance criteria

1. [unit] `AdjudicationResult` schema: `{final: RemittanceExtraction, provenance: dict[field_path, "A"|"B"|"both"], line_provenance: list[{line_no, source: "A"|"B"|"both"}], disagreements: list[{field_path, value_a, value_b, chosen, reason}], confidence: float 0-1}`; prompt with `PROMPT_VERSION`.
2. [integration] One Alembic revision creates `ADJUDICATION` (ID, WORK_ITEM_ID, ORIGIN (MODEL|HUMAN), MODEL_ID, PROMPT_VERSION, SCHEMA_VERSION, READING_A_ID, READING_B_ID, MISSING_READER (A|B|null), FINAL JSON, PROVENANCE JSON, DISAGREEMENTS JSON, CONFIDENCE, EDITED_BY, CREATED_AT, PURGED_AT). `AdjudicationRepository.latest_for(item_id) -> Adjudication | None` (HUMAN rows supersede MODEL rows by CREATED_AT) is the single accessor every later station uses for "the current extraction".
3. [integration] `AdjudicateRunner` (stage ADJUDICATE) loads the latest reading per reader (by ATTEMPT). Both OK → one `llm.adjudicator.parse` call whose request contains only the two JSON outputs (test asserts no artifact part / image / PDF content in the request). One OK → no adjudication call needed: the single reading becomes `final` with provenance all from that reader, `MISSING_READER` recorded, confidence = that reader's mean field confidence × `0.8`. Both failed → `StageError(EXTRACTION_FAILED)`.
4. [integration] The stored row links both raw readings (READING_A_ID/READING_B_ID) and records prompt/schema version; outcome `Advance(VALIDATE)`; `confidence < config.escalation().min_extraction_confidence` raises `StageError(LOW_EXTRACTION_CONFIDENCE)` after storing the row.
5. [unit] Refusal/transient handling as in s07 (`LLM_REFUSAL`/`LLM_TRANSIENT`); effort from `config.models().adjudicator`.
6. [unit] `save_human_correction(uow, item_id, final: RemittanceExtraction, principal) -> Adjudication` (ORIGIN=HUMAN, provenance "human") is public for s18's requeue.
7. [unit] `ROLE = RoleSpec("adjudicate", "consumer", build)`.

## Out of scope

Validation (s10); usage rows (s36).

## Deps

- s08-extraction-fan-out — `EXTRACTION_READING` columns, `RemittanceExtraction`, `LlmClients.adjudicator`, `ReplayLlmClient`, `make_extraction`. plannable.
- s03-pipeline-runtime — `StageRunner`, `StageError`, `Advance`. plannable.
- s28-runtime-config-service — `config.models().adjudicator`, `config.escalation().min_extraction_confidence`. plannable.
- s30-worker-host — `RoleSpec`. plannable.

## Assumptions

- With one reader missing, no adjudicator call is made (it would only echo); the decision still records which reader was missing. Logged as an interpretation of the issue AC3.
