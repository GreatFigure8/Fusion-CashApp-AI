# s17-fusion-write-back: Write-back (receipt note and remittance attachment in Fusion)

- Issue: #17
- Wave: 5 (money path; owns `cashapp/stations/write_back/`, `cashapp/services/write_back.py`, `cashapp/services/receipt_note.py`)
- breaking: false

## Story

As someone working in Fusion, I want to see on the receipt itself what the automation did and why, with the remittance attached, so that I never need to open another system to understand an application.

## Context

Reference doc §1 ("tell the story in Fusion"; the receipt note field is small). The attachment and note endpoints must be confirmed on a non-production pod before they're built (s05 marks them UNVERIFIED); until credentials exist this story builds against `FakeFusionClient` and the live probe test confirms later. A write-back failure never undoes applications; it has its own error code `WRITE_BACK_FAILED`.

## Acceptance criteria

1. [integration] Confirmation first: a `-m live` probe test confirms the receipt note field (name and max length) and the attachment endpoint on the dev pod via `FusionClient` (or `aix-greenlight` `fusion_rest_describe` during coding), and `integrations/fusion/CONTRACTS.md` is updated; until confirmed, the field length is the setting `fusion.receipt_note_max_chars` (default 240) and the code paths are marked UNVERIFIED.
2. [unit] `compose_receipt_note(item, line_results, max_chars) -> str`: deterministic, e.g. `CashApp WI-20481 2026-10-23: applied 5/7 (USD 12,480.00). Failed: INV-1044 not found; INV-1050 no balance. See app.` — counts first, then failed lines with short reasons, truncated with `…+N more` to fit `max_chars`; never contains payer names or email content beyond transaction numbers; Haiku is NOT required (code template); appends to an existing note rather than overwriting (keeps the previous text if it fits, else replaces with a marker).
3. [unit] `write_back(uow, item, receipt_id, *, mode) -> WriteBackResult{note_written, attachment_ref}`: attaches the original artifact (`ObjectStore.get(ARTIFACT_KEY)`, filename `remittance-WI-<id>.<ext>`, `.eml` for emails) and sets the note via `fusion.set_receipt_comment`; idempotent (an attachment with the same title already present is not re-added; checked via list call or a recorded `attachment_ref` in history).
4. [integration] `WriteBackRunner` (stage WRITE_BACK): calls `write_back(mode="applied")`, records a FUSION_WRITE history row, `Finish(item.PAYMENT_STATUS)` → STATE=DONE. Any failure raises `StageError(WRITE_BACK_FAILED)` WITHOUT touching `APPLICATION_LEDGER` or `LINE_RESULT` (test asserts ledger unchanged); transient causes are retried by s18 within the limit, then escalated.
5. [unit] `fusion.write_enabled=false` → `WRITE_BACK_FAILED` with detail `FUSION_WRITE_DISABLED`, applications untouched.
6. [unit] `ROLE = RoleSpec("write-back", "consumer", build)`.

## Out of scope

Applications (s15); fast path decision (s16 calls `write_back`).

## Deps

- s05-fusion-client — `set_receipt_comment(receipt_id, text)`, `attach_to_receipt(receipt_id, filename, content, content_type, title) -> AttachmentRef` (UNVERIFIED until AC1). unplannable for the live contract (needs pod credentials); plannable against the fake.
- s15-line-matching-apply — `LINE_RESULT` rows, `APPLICATION_LEDGER`, `Advance(WRITE_BACK)`. plannable.
- s06-intake-poller — `ObjectStore.get`, `WORK_ITEM.ARTIFACT_KEY`. plannable.
- s03-pipeline-runtime — `StageRunner`, `Finish`. plannable.

## Assumptions

- Note format is a code template (cheaper and deterministic); a Haiku-written note can replace it later if wanted.
