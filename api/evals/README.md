# Evaluation harness

Measures a model or rule change against cases with known answers, so a change is judged before it
ships. It is a command you run on purpose. It is never run by CI, and the default `pytest` run
makes no live call.

```
uv run python -m cashapp.evals run --suite extraction|matching|autofix|all
    [--limit N] [--replay] [--runs N] [--confirm-spend]
    [--out DIR] [--gold DIR] [--prior DIR] [--recordings DIR] [--config FILE]
```

Run it from `api/` or from the repository root. The report goes to
`api/evals/reports/<UTC timestamp>/` as `report.md` (for reading) and `report.json` (the stable
format, for comparing two runs). Reports are gitignored and never overwritten: `--out` must be a
new directory.

Exit codes: `0` report written; `1` a selected suite was `not_evaluated` (no cases found, or the
suite failed), or the run failed; `2` bad arguments, an existing `--out`, or the spend guard
refused.

## The suites

| Suite | What it does | Model calls |
|---|---|---|
| `extraction` | Reader A, reader B and the adjudicator on every gold case, scored per field and per transaction line | Yes (unless `--replay`) |
| `matching` | The prior build's messages (`tests/fixtures/prior`) through customer resolution, receipt scoring and line planning against a fake Fusion | No |
| `autofix` | Each of AR's labelled failures through the auto-fix engine, compared with the decision its label expects | No |

A suite that finds zero cases reports `not_evaluated` with the reason and the run exits 1. An
empty set is never a clean score.

The matching and auto-fix numbers are **agreement** with the prior build's outcomes and AR's
labels, not accuracy: that build had known defects, so a disagreement may mean the new rules are
right.

## Cost

A live extraction run calls Opus twice (reader A and the adjudicator) and Cohere once per case,
times `--runs`. It is refused unless you pass `--confirm-spend`:

```
refusing: a live extraction run calls Opus x2 + Cohere per case (N cases x runs); re-run with --confirm-spend or --replay
```

The refusal happens before settings are read or any client is built. `--replay` costs nothing.
`report.json` carries the run's tokens and USD (`cost`), priced with the s36 table. In replay the
recorded usage is shown as `recorded_usage_usd` and `spent_usd` is `0.00`. The daily budget alert
does not see eval usage (it is kept in memory, not in the ledger), and there is no budget cap
inside the harness: use `--limit` and `--runs` to bound a run.

## Replay and live

- `--replay` answers every model call from `api/evals/recordings/` (an `s08` `ReplayLlmClient`),
  keyed by purpose and by a digest of the content parts. The committed recordings are
  **synthetic** (`verified_against_live: false`) with deliberate reader mistakes. They prove the
  harness works; they say nothing about model quality.
- A live run calls the real models, with the models, effort and timeouts from the runtime
  configuration defaults. `--config FILE` overlays `{config_key: value}` overrides (validated
  like the configuration screen), so a model or rule change is measured before it is saved:

  ```json
  {"models.reader_a": {"model_id": "claude-opus-5-5", "effort": "max", "timeout_s": 180},
   "matching.date_window_days": 7}
  ```

- A live run saves every call to `<out>/outputs/<case>/<run>/<purpose>.json` in the recording
  shape. To turn a live run into the replay set, copy those files into `api/evals/recordings/`
  as `<case>.<purpose>.json`.
- The replay key covers the content parts only, not the system prompt. After changing a prompt,
  re-record from a live run; the report shows `prompt_versions` so you can tell.
- `--runs N` repeats each extraction case: one stochastic pass measures little.

## Gold files

`api/evals/gold/<case_id>.json`, one per artifact in `api/evals/artifacts/`:

```json
{"case_id": "g01_credit_memo_suffix", "synthetic": true, "artifact": "g01_credit_memo_suffix.txt",
 "tags": ["suffix"], "expected": {"payer_name": "...", "payment_amount": "2350.00", "lines": []}}
```

In `expected`, a field that is left out is not scored; a field set to `null` (or an empty list)
means the value must be absent. That is how the negative cases work: g03 expects `currency: null`
with `currency_ambiguous: true`, so a reader that guesses a dollar is marked wrong.
`lines` are scored on the multiset of transaction numbers; suffixes count (`2598014` and
`2598014-1` are different documents).

The committed set is six synthetic remittances with invented payer names (suffix and credit memo,
lines without amounts, a bare `$`, several dates, a bank fee, a whole-rupee INR table with PO
references). Gold extractions for real fixtures are made by a person later. After changing an
artifact or a gold file, rebuild the recordings:

```
uv run python evals/build_recordings.py
```

## What is reused

The harness holds no second copy of any station logic: content loading and limiting, the reader
and adjudicator requests, the single-reader rule and the grounding check come from the extract
and adjudicate stations; customer resolution, receipt scoring and line planning from the matching
services; the engine through `FailureHandler.handle`; metering and prices from the usage ledger;
the label-to-decision mapping and the fixture loaders from the anonymiser. The auto-fix suite uses
an in-memory SQLite database (needs the dev dependency group, which `uv run` installs).
