# CashAppRelationships report definition

| Item | Value |
|---|---|
| Data model name | `CashAppRelationships` |
| Data model SQL | `relationships.sql` |
| Data set | `DATA_DS` (SQL Query, data source `ApplicationDB_FSCM`) |
| Parameter | `P_ACCOUNT_NUMBERS`, text, comma-separated account numbers, no default, not multi-select |
| Output format | XML (data-model-only report, no layout; HTML fails) |
| Layout | none |
| Catalog path | `/Custom/CashApp/CashAppRelationships.xdo` |
| Setting | `fusion.relationships_report_path` (`CASHAPP_FUSION__RELATIONSHIPS_REPORT_PATH`) |

## Output shape

Root `DATA_DS`; one `G_1` element per row with the children below. The Fusion client parses
exactly these names and deduplicates an account related in both directions.

| Element | Meaning |
|---|---|
| `ACCOUNT_NUMBER` | the account that was asked about |
| `RELATED_ACCOUNT_NUMBER` | the related account |
| `RELATED_ACCOUNT_NAME` | the related account's party name |
| `DIRECTION` | `OUTBOUND` or `INBOUND` |

A parameter that matches no account returns a well-formed `DATA_DS` with no `G_1` rows. The
preflight relies on that for its known-empty check.
