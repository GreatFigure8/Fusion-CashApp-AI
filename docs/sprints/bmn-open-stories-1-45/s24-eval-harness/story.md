# s24-eval-harness: Eval set and harness for extraction, matching and auto-fix

- Issue: #24
- Wave: 5 (needs the matcher; owns `cashapp/evals/`, `api/evals/`)
- breaking: false

## Story

As the person changing models and rules, I want model and rule changes judged by measurement against real (anonymised) cases, so that we know a change helped before it ships.

## Context

Uses s43's fixtures. Every run that calls a model spends money: runs are deliberate (a command), never automatic, never in CI. Matching/auto-fix evals run against `FakeFusionClient` seeded from the fixtures and need no model calls.

## Acceptance criteria

1. [unit] `uv run python -m cashapp.evals run --suite extraction|matching|autofix|all [--limit N] [--replay] --out api/evals/reports/<timestamp>/` produces `report.md` and `report.json`.
2. [unit] Extraction suite: for each fixture artifact with a gold extraction (`api/evals/gold/*.json`), runs Reader A, Reader B and the adjudicator through the same station code paths (or `--replay` with `ReplayLlmClient` recordings, zero cost) and measures per-field accuracy (exact for strings after normalisation, `money_eq` for amounts, date equality), line-level precision/recall on transaction numbers, per reader and after adjudication.
3. [unit] Matching suite: replays `prior/day` and `prior/labelled` through customer resolution, receipt scoring and line planning against the seeded fake; reports agreement with AR's labels (confusion matrix over the four labels) and line-status agreement.
4. [unit] Auto-fix suite: feeds each labelled failure's error code to the engine and reports decision agreement with the expected decision from s43's label mapping.
5. [unit] The report includes run cost: sums `LlmUsage` of every call made during the run (tokens and USD using s36's `PRICES`) and refuses to start a non-replay run without `--confirm-spend` (test).
6. [unit] A tiny gold set (≥ 5 synthetic remittances covering suffixes, no-amount lines, `$`, multiple dates, bank fee) is committed under `api/evals/gold/`.

## Out of scope

CI integration; dashboards.

## Deps

- s43-anonymised-prior-fixtures — fixture format `prior/day/messages.jsonl`, `prior/day/fusion.json`, `prior/labelled/failures.jsonl`, label→decision mapping. plannable (earlier wave).
- s08-extraction-fan-out — readers, `ReplayLlmClient`, `RemittanceExtraction`. plannable.
- s09-adjudicate-fan-in — adjudication call path. plannable.
- s11-customer-resolution — `resolve_customer(...)`. plannable.
- s18-auto-fix-engine — `AutoFixEngine` decisions. plannable.
- s36-llm-usage-cost-ledger — `PRICES`, `LlmUsage` cost computation. plannable.
- s13-receipt-matching-scorer — `score_candidates(item_ctx, receipts, config, aliases) -> ScoredCandidates` from `cashapp/services/matching/receipts.py`. plannable (same wave).
- s15-line-matching-apply — `plan_lines(lines, transactions, receipt_remaining, existing_applications) -> LinePlan` from `cashapp/services/matching/lines.py`. plannable (same wave).

## Assumptions

- Gold extractions for real fixtures are produced by a person later; the synthetic gold set proves the harness.
