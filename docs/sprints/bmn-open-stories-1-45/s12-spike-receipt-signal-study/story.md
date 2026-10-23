# s12-spike-receipt-signal-study: Spike — receipt-signal study on a Fusion pod with real cash activity

- Issue: #12
- Wave: 4 (owns `docs/spikes/receipt-signals.md`, `cashapp/tools/receipt_signal_study/`)
- breaking: false

## Story

As the builder of the receipt scorer, I want to know from real data which fields actually link a remittance to its receipt, so that s13's scorer uses evidence instead of amount-only matching.

## Context

Read-only. Blocked until Jonathan names the pod, so this story is built against fakes: it delivers the repeatable, read-only study tool (run against `FakeFusionClient` + anonymised fixtures now, against the named pod later) and a proposal with provisional weights clearly marked "provisional — not yet measured". No client or customer identifiers in the write-up.

## Acceptance criteria

1. [unit] `uv run python -m cashapp.tools.receipt_signal_study --pod <name> --from <date> --to <date> --out <dir>` reads (only via `FusionClient` read methods and BIP `run_query`-style reports; never a write method — enforced by a test that the tool's client wrapper raises on any write) receipts with their remittance references, bank statement lines (reference, addenda, payer name), payer bank accounts and receipt comments, plus applications to know the right answer.
2. [unit] For each signal (amount exact/within tolerance, date distance by receipt_date vs creation_date, currency, customer/related customer, remittance reference, statement-line reference, addenda text, payer name, payer bank account, comments, invoice-set overlap) it computes presence rate and precision (how often the signal alone identifies the receipt that was actually applied); output CSV + JSON, aggregated only (no identifiers).
3. [unit] Run against the fake/fixtures, it produces the report end to end (test).
4. [unit] `docs/spikes/receipt-signals.md` proposes s13's signals and starting weights as `matching.scorer_weights` JSON (keys = signal names s13 implements) and `matching.min_score`, marked provisional until the study runs on the named pod; lists the open question (pod name) at the top.
5. [unit] Scan test: the spike document and tool output templates contain no customer names or account numbers (reuses s43's scanner when present, else a regex for account-like numbers).

## Out of scope

Implementing the scorer (s13).

## Deps

- s05-fusion-client — read methods, `run_report`, `FakeFusionClient`. plannable.
- s43-anonymised-prior-fixtures — `api/tests/fixtures/prior/` format and `scan_for_identifiers(text) -> list[Finding]`. plannable for the scanner and fixture format (same wave); unplannable for real data (the source data and the pod need Jonathan), so the spike runs on `FusionScenario` fakes now.

## Assumptions

- Bank statement lines are read through a BIP data model (cash management tables) defined in s32's catalog; until then the tool skips that signal and says so.
