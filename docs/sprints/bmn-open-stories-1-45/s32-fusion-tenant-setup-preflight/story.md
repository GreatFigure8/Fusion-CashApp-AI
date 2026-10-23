# s32-fusion-tenant-setup-preflight: Fusion tenant setup kit and preflight check

- Issue: #32
- Wave: 4 (owns `fusion/`, `cashapp/tools/preflight/`)
- breaking: false

## Story

As the person onboarding a Fusion pod, I want everything the pod needs scripted or documented and checkable automatically, so that the system never starts against a half-configured tenant.

## Context

Reference doc §3: the pay-on-behalf relationships BIP report must be built in each tenant (XML output, filters `status='A'`, `bill_to_flag='Y'`, date-effective; returns INBOUND and OUTBOUND rows). Read-only checks; never writes to a production pod. Built against fakes; the live check runs once credentials exist.

## Acceptance criteria

1. [unit] `fusion/SETUP.md` documents the integration user and the exact duty/job roles needed for: REST reads (`receivablesInvoices`, `receivablesCreditMemos`, `standardReceipts`, customer accounts), SOAP `StandardReceiptService` apply/unapply, BIP `ExternalReportWSSService` runReport, receipt attachments and comments; each marked "confirm on pod" until confirmed; plus the settings/Vault secrets to create per pod.
2. [unit] `fusion/bip/` keeps the relationships report as a data model SQL (`relationships.sql`) and report definition, with catalog export placeholders (`*.xdmz`/`*.xdoz` produced by exporting from the dev pod) and step-by-step deploy instructions (upload to `/Custom/CashApp/`, set path in `fusion.relationships_report_path`); also the optional receipt/bank-statement lookup data model used by s12 (`receipt_signals.sql`).
3. [unit] `uv run python -m cashapp.tools.preflight --pod <name>` runs read-only checks and prints a pass/fail table and exit code: auth (a cheap REST GET), each REST resource with `REST-Framework-Version: 4` + an `in (...)` `q=` (proves the header behaviour), `hasMore` pagination works, SOAP service WSDL reachable (GET `?WSDL` only), BIP report present and returns XML for a known-empty parameter, attachments endpoint describable, `fusion.write_enabled` value and pod `is_production` flag shown.
4. [unit] The preflight uses only read methods; a test runs it against a wrapper that raises on any write and against `FakeFusionClient` (all pass) and a fake missing the report (report check fails, exit code 1).
5. [integration] `-m live`: run preflight on the configured dev pod; skipped without credentials.

## Out of scope

Creating the BIP report in a tenant (a person does it from the docs); test data (s23).

## Deps

- s05-fusion-client — read methods, `run_report`, `rest_get`, `FakeFusionClient`. plannable.
- s27-settings-secrets-wiring — `Settings.fusion.pods`, `relationships_report_path`. plannable.

## Assumptions

- Catalog exports can only be produced from a pod; the repo holds SQL + definition until then.
