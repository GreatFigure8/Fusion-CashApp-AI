# BI Publisher data models and reports

> **Superseded 2026-10-23 (fusion-mcp-transport).** The two SQL files moved to
> `api/src/cashapp/integrations/fusion/datamodels/` (one packaged copy). The app now runs them as
> ad-hoc SQL through the fusion-sql-mcp server's `run_query`, so **creating these catalog reports
> is no longer required** and the deploy steps below are optional (kept for reference and for
> checking the SQL by hand in the BI Publisher data model editor). The definitions in `*.report.md`
> still describe the row shape.

Two data-model-only reports live here as SQL plus a definition. A person creates them in each
Fusion pod from these files (the system never uploads to a catalog).

| Report | Required | Used by | SQL | Definition |
|---|---|---|---|---|
| `CashAppRelationships` | yes | customer resolution and receipt search (pay-on-behalf) | `datamodels/relationships.sql` (in the API package) | `relationships.report.md` |
| `CashAppReceiptSignals` | optional | receipt and bank-statement lookup | `datamodels/receipt_signals.sql` (in the API package) | `receipt_signals.report.md` |

All table and column names in the SQL are from vendor knowledge and carry `UNVERIFIED` comments.
Confirm them against the pod (the Data Model editor's schema browser, or a read-only
describe-table probe on a non-production source) before you rely on the output.

## Deploy steps

Do these in the BI Publisher catalog of the pod, signed in as a user with BI Author access.

1. Open the BI Publisher catalog and create the folder `/Custom/CashApp/` (skip if it exists).
2. Create a new data model in that folder named `CashAppRelationships`.
3. Add a data set of type SQL Query, name it `DATA_DS`, data source `ApplicationDB_FSCM`, and
   paste the contents of `relationships.sql`.
4. Add the parameter `P_ACCOUNT_NUMBERS` (text, comma-separated list, no default) as described in
   `relationships.report.md`.
5. In the data model's properties set the output to XML and add no layout. The report is
   data-model-only: asking for HTML fails.
6. Save, then use "Get XML Output" with an unknown account number to confirm the result is a
   `DATA_DS` root with zero `G_1` rows, and with a known pay-on-behalf account to see rows.
7. Create a report on the data model named `CashAppRelationships` (no layout template) so the
   catalog path is `/Custom/CashApp/CashAppRelationships.xdo`.
8. Grant the integration user read permission on the data model and the report.
9. Set `fusion.relationships_report_path` through its environment variable
   `CASHAPP_FUSION__RELATIONSHIPS_REPORT_PATH` to `/Custom/CashApp/CashAppRelationships.xdo`.
10. Optional: repeat steps 2 to 8 for `CashAppReceiptSignals` with `receipt_signals.sql` and
    `receipt_signals.report.md`. Its path is passed as an option by the tool that uses it; it is
    not a setting.
11. Export both data models (`*.xdmz`) and both reports (`*.xdoz`) from the dev pod catalog
    ("More, Export") and commit them under `fusion/bip/catalog/`, then update the status table in
    `catalog/README.md`.
12. Run the preflight (`uv run python -m cashapp.tools.preflight --pod <name>`). The
    `bip.relationships_report` row must show PASS.
