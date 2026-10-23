# Receipt signals: which fields link a remittance to its receipt

## Open question

**Which Fusion pod has real cash activity?** The study tool is built and runs end to end, but until
Jonathan names the pod it has only run against the fake client and the synthetic prior fixtures.
Every weight below is therefore **provisional — not yet measured**.

## What exists

`uv run python -m cashapp.tools.receipt_signal_study --pod <name> --from <date> --to <date> --out <dir>`

- Read-only. The client is wrapped by `read_only()`, so any write method raises
  `FUSION_WRITE_DISABLED`. Reads are receipts (by creation time), their applications (the right
  answer), transactions, pay-on-behalf relationships and, when `--signals-report <bip path>` is given,
  the bank statement lines (reference, addenda, payer name, payer bank account).
- Output is aggregate only: `signals.csv`, `signals.json`, `run.json`. Rows are keyed by signal name.
  Payer bank accounts are hashed in memory and never written.
- Case sources: Fusion-only (default; the remittance is reconstructed from the applied receipt, so
  amount, receipt date and currency are flagged `circular`) or `--prior <dir>` (real remittances
  against Fusion truth, the true measure).
- Per signal: `presence_rate` (case and truth receipt both carry the value), `precision` (the signal
  alone picks out exactly the applied receipt), `ambiguous_rate` (applied receipt among two or more
  matches), `miss_rate` (applied receipt not matched), plus date-distance histograms for receipt date
  and creation date.

## Signals

| Signal | Kind | Rationale |
|---|---|---|
| currency | hard filter | Receipt and remittance must agree. |
| amount exact / within tolerance | hard filter | Duplicate amounts are common, so amount alone is ambiguous; it narrows, it does not decide. Tolerance is per currency (`matching.tolerances`). |
| date window (receipt date) | hard filter | `matching.date_window_days`, shared with the Fusion query. |
| date window (creation date) | hard filter, second basis | Receipts are often created a day after their receipt date; match on both bases. |
| customer anchor / related customer | hard filter | Anchor-owned receipts first, then pay-on-behalf related customers. |
| remittance reference | soft | Strongest direct link when the payer quotes the receipt reference. |
| invoice-set overlap | soft | Receipt references that name the invoices being paid. |
| statement-line reference | soft | Bank reference on the statement line behind the receipt. |
| payer bank account | soft | Stable per payer; compared as a hash. |
| addenda text, comments | soft, folded into reference and overlap | They carry the same references in free text; measured separately, scored through the signals above. |
| payer name | alias evidence | Feeds `alias_reference_pattern` rather than a weight of its own. |
| date distance | soft | Closer dates break ties inside the window. |
| customer history | soft | Prior pairings of this payer with this customer's receipts. |

Reference normalisation (shared with s13): upper-case, remove whitespace, strip leading zeros.
Invoice numbers stay strings.

## Proposal for s13 (provisional — not yet measured)

Hard filters (currency, amount tolerance or bank-fee band, date window, anchor or related owner) are
filters, not weights. Each soft signal contributes `weight x strength` (strength in 0..1). If more
than one receipt qualifies, the winner must beat the runner-up by `matching.min_score`, otherwise it
is an ambiguity (`FIX_HINTS.narrow`), never "first wins".

```json
{"matching.scorer_weights": {"remittance_reference": 0.35, "invoice_set_overlap": 0.30,
  "statement_reference": 0.15, "payer_bank_account": 0.10, "date_distance": 0.05,
  "alias_reference_pattern": 0.03, "customer_history": 0.02},
 "matching.min_score": 0.15}
```

The weights sum to 1.0. This story does not write them to runtime configuration; the default stays
empty until s13 decides whether to seed them.

## Replacing the numbers once the pod is named

1. Deploy the `receipt_signals` report from the s32 catalog on that pod (needed for the four
   statement-line signals; without it they are listed as skipped in `run.json`).
2. Run the tool with `--prior` against the real remittances, then once Fusion-only for the wider
   picture.
3. Order the soft signals by `precision`, check `ambiguous_rate` and `miss_rate`, and note how many
   truth receipts only `date_creation_window` catches.
4. Update `matching.scorer_weights` and `matching.min_score` from the configuration screen (s21) with
   a CONFIG_CHANGE reason citing the study run, and remove the provisional marking here.
