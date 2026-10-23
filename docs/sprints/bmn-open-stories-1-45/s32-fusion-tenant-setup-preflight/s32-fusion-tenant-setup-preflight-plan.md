# Plan: s32-fusion-tenant-setup-preflight

Issue #32. Wave 4. Owns repo-root `fusion/` and `api/src/cashapp/tools/preflight/`. Paths:
`cashapp/` = `api/src/cashapp/`. No UI (design.md not involved), no LLM, no migration.
Built against s05's pinned `FusionClient` / `FakeFusionClient` / `read_only` and s27's pinned
`Settings.fusion`. Every live fact not yet confirmed on a pod is marked "confirm on pod" (docs) or
`# UNVERIFIED:` (code, with a row in s05's `CONTRACTS.md`).

## Standards followed

- CLAUDE.md *Fusion integration*: all traffic through the one `FusionClient` (no second HTTP stack
  in the tool); `REST-Framework-Version: 4`; `hasMore` pagination; `q=` built only with s05's
  `q_literal`/`q_in`; BIP `runReport` asking for XML; "never guess an endpoint" (every candidate
  name is UNVERIFIED until the live preflight or `aix-greenlight` read-only probes confirm it).
- research.md a6 rails: the preflight always wraps its client in s05's `read_only()` (one
  implementation, no local guard). It never needs `fusion.write_enabled`; it only reports it.
- research.md "two implementations": the preflight runs against `HttpFusionClient` or
  `FakeFusionClient`; no third fake.
- CLAUDE.md *Conventions*: no client/customer names in docs, SQL, fixtures; check failure text holds
  only error code, HTTP status and Fusion code (never bodies, query strings or credentials).
- `python-web-app:building-python-web-apps`: logic in a plain async service module
  (`checks.py`), CLI is a thin typer shell (typer pinned by s01, same pattern as s30's
  `workers/cli.py`); settings loaded once via s27's `load_settings`, never read inside checks.
- pyright strict, ruff; frozen slotted dataclasses for the report types (matches s05 style).

## Files to touch

New (owned by this story):

| Path | Contents |
|---|---|
| `fusion/SETUP.md` | integration user, roles per capability, data access, settings and Vault secrets per pod, onboarding checklist ending in "run preflight" (AC1) |
| `fusion/bip/README.md` | step-by-step deploy of both data models/reports (AC2) |
| `fusion/bip/relationships.sql` | pay-on-behalf data model SQL, row shape pinned by s05 |
| `fusion/bip/relationships.report.md` | report definition: data model name, data set, parameter, output format XML, no layout, catalog path |
| `fusion/bip/receipt_signals.sql` | optional receipt / bank-statement lookup data model for s12 (shape pinned below) |
| `fusion/bip/receipt_signals.report.md` | its report definition |
| `fusion/bip/catalog/README.md` | placeholder register for `CashAppRelationships.xdmz`, `CashAppRelationships.xdoz`, `CashAppReceiptSignals.xdmz`, `CashAppReceiptSignals.xdoz`: status "not yet exported", how to export from the dev pod, where to commit |
| `api/src/cashapp/tools/preflight/__init__.py` | re-exports `run_preflight`, `PreflightContext`, `PreflightReport`, `CheckResult`, `CheckStatus`, `render_table` |
| `api/src/cashapp/tools/preflight/__main__.py` | `from cashapp.tools.preflight.cli import app; app()` |
| `api/src/cashapp/tools/preflight/cli.py` | typer `app` (single command), `make_client(settings, pod)` (patch point for tests) |
| `api/src/cashapp/tools/preflight/checks.py` | the check list, `run_preflight` |
| `api/src/cashapp/tools/preflight/report.py` | `CheckStatus`, `CheckResult`, `PreflightReport`, `render_table` |
| `api/tests/fixtures/fusion/soap/standard_receipt_service.wsdl` | minimal WSDL shape (fake + respx) |
| `api/tests/unit/tools/test_preflight_checks.py` | AC3/AC4 service tests |
| `api/tests/unit/tools/test_preflight_cli.py` | AC3/AC4 CLI tests |
| `api/tests/unit/tools/test_fusion_setup_docs.py` | AC1 |
| `api/tests/unit/tools/test_fusion_bip_catalog.py` | AC2 |
| `api/tests/live/fusion/test_preflight_live.py` | AC5 |

Edited (owned by s05, merged in wave 1; small additive read surface, see Assumptions):

| Path | Change |
|---|---|
| `api/src/cashapp/integrations/fusion/client.py` | `FusionClient.get_raw` on the Protocol; `HttpFusionClient.get_raw` |
| `api/src/cashapp/integrations/fusion/transport.py` | `get_bytes(path, params)` (GET, basic auth, read retry policy, span, no RFV/onlyData/JSON parsing) |
| `api/src/cashapp/integrations/fusion/fake.py` | `get_raw` (serves `raw: Mapping[str, bytes]` ctor arg; defaults: WSDL for `SOAP_PATH_RECEIPTS` and `BIP_PATH` with `?WSDL`, `standardReceipts/describe` JSON listing an `attachments` child); `rest_get` also serves the customer-account resource with `AccountNumber in`, and returns `hasMore`/`count`/`limit`/`offset` honouring `limit`/`offset` (only if s05 did not already) |
| `api/src/cashapp/integrations/fusion/guard.py` | `read_only` delegates `get_raw` (only if it delegates by explicit method list) |
| `api/src/cashapp/integrations/fusion/query.py` | `CUSTOMER_ACCOUNTS_PATH` constant only if s05 left the customer-account path inline in `client.py` (one constant, both use it) |
| `api/src/cashapp/integrations/fusion/CONTRACTS.md` | rows: WSDL GET for both SOAP services, `standardReceipts/describe` attachments child, BIP report paths, both SQL data models (all UNVERIFIED) |

No `pyproject.toml`/lockfile, settings, router, or Alembic edits. Test basenames are prefixed
`test_preflight_` / `test_fusion_setup_` / `test_fusion_bip_` so they cannot collide.

## Design

### Preflight service (`checks.py`)

`run_preflight(client, ctx)` runs the checks below **in order, each isolated**: a check catches
`FusionError` (status FAIL, detail `"<code> http=<status> fusion=<code>"`), `TimeoutError`
(FAIL, `"timeout"`) and any other `Exception` (FAIL, exception class name only). Each check gets
`asyncio.timeout(ctx.check_timeout_s)`. A failed auth check does not short-circuit the rest (the
table then shows every failure; operators see the whole picture). Probe literals are fixed sentinels
that cannot exist: `PROBE_VALUES = ("CASHAPP-PREFLIGHT-0", "CASHAPP-PREFLIGHT-1")`.

| # | Check name | Call | PASS when |
|---|---|---|---|
| 1 | `auth` | `client.rest_get("receivablesInvoices", {"limit": "1", "fields": "CustomerTransactionId"})` | returns a dict with `items` |
| 2 | `rest.receivablesInvoices` | `rest_get(..., {"q": q_in("TransactionNumber", PROBE_VALUES), "fields": ..., "limit": "1"})` | 200 with `items == []` (a 400 here means the RFV header behaviour is wrong) |
| 3 | `rest.receivablesCreditMemos` | same, `TransactionNumber` | same |
| 4 | `rest.standardReceipts` | same, `ReceiptNumber`, plus `expand=remittanceReferences` | same |
| 5 | `rest.customerAccounts` | s05's customer-account path, `AccountNumber in (...)` | same |
| 6 | `rest.pagination` | `rest_get("standardReceipts", {"limit": "1", "offset": "0", "fields": "StandardReceiptId"})`; if `hasMore` is true, a second call at `offset=1` | `hasMore` is a bool; when true the second page returns ≥1 item with a different id; when false: PASS with detail "single page on pod" |
| 7 | `soap.StandardReceiptService.wsdl` | `client.get_raw(SOAP_PATH_RECEIPTS, {"WSDL": ""})` | defusedxml parses it, root local-name `definitions`, and an operation `createApplyReceipt` is present |
| 8 | `bip.ExternalReportWSSService.wsdl` | `client.get_raw(BIP_PATH, {"WSDL": ""})` | parses, operation `runReport` present |
| 9 | `bip.relationships_report` | `client.run_report(ctx.relationships_report_path, {RELATIONSHIPS_PARAM: PROBE_VALUES[0]}, "xml")` | defusedxml parses, root `DATA_DS`, zero `G_1` rows |
| 10 | `rest.attachments` | `client.rest_get("standardReceipts/describe")` | the describe JSON lists a child resource named `attachments` (UNVERIFIED path/shape) |
| 11 | `config.write_enabled` | none | INFO, detail `true`/`false` |
| 12 | `config.pod_is_production` | none | INFO, detail `true`/`false`; plus `env=<env>` |

INFO rows never change the exit code. Overall `ok = all(r.status != FAIL)`.

Only read methods are called (`rest_get`, `get_raw`, `run_report`); `run_report` is a SOAP POST but
a read (it is not in s05's `WRITE_METHODS`).

### CLI (`cli.py`)

`uv run python -m cashapp.tools.preflight --pod <name> [--timeout 30]`:
1. `load_settings()`; `SettingsError` → message (names only) on stderr, exit 2.
2. Unknown pod → stderr lists known pods, exit 2.
3. `client = read_only(make_client(settings, pod))` where `make_client` =
   `FusionClientFactory(settings).for_pod(pod)`; `async with`/`aclose()` always.
4. `report = asyncio.run(run_preflight(client, ctx))`; print `render_table(report)` to stdout;
   exit 0 if `report.ok` else 1.

`render_table`: fixed-width plain text (no new dependency), columns `CHECK | STATUS | DETAIL`,
header line `Fusion preflight: pod=<name> env=<env>`, footer `RESULT: PASS|FAIL (<n> failed)`.

## Interfaces provided (pinned)

```python
# cashapp/tools/preflight/report.py
class CheckStatus(StrEnum): PASS = "PASS"; FAIL = "FAIL"; INFO = "INFO"

@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str; status: CheckStatus; detail: str; elapsed_ms: int

@dataclass(frozen=True, slots=True)
class PreflightReport:
    pod_name: str; env: str; results: tuple[CheckResult, ...]
    @property
    def ok(self) -> bool                       # no FAIL
    def result(self, name: str) -> CheckResult  # KeyError if absent

def render_table(report: PreflightReport) -> str

# cashapp/tools/preflight/checks.py
PROBE_VALUES: tuple[str, str]
CHECK_NAMES: tuple[str, ...]                   # the 12 names above, in order

@dataclass(frozen=True, slots=True)
class PreflightContext:
    pod_name: str; env: str; is_production: bool; write_enabled: bool
    relationships_report_path: str; check_timeout_s: float = 30.0
    @classmethod
    def from_settings(cls, settings: Settings, pod_name: str, *, check_timeout_s: float = 30.0) -> PreflightContext

async def run_preflight(client: FusionClient, ctx: PreflightContext) -> PreflightReport

# cashapp/tools/preflight/cli.py
app: typer.Typer
def make_client(settings: Settings, pod: str) -> FusionClient   # patch point

# additions to s05 (cashapp/integrations/fusion/client.py)
class FusionClient(Protocol):
    async def get_raw(self, path: str, params: Mapping[str, str] | None = None) -> bytes: ...
        # plain GET, read retry policy; absolute path (starts with "/") or relative to REST_BASE;
        # no JSON parsing, no RFV/onlyData; non-2xx → FusionError via error_from_http
# FakeFusionClient.__init__ gains: raw: Mapping[str, bytes] | None = None   (key = path, query ignored)
```

### BIP data models (pinned for consumers)

**Relationships** (`fusion/bip/relationships.sql`; consumer s05 `parse_relationships_xml`): exactly
s05's pinned shape. Parameter `:P_ACCOUNT_NUMBERS` (comma-separated, split in SQL with a
`REGEXP_SUBSTR … CONNECT BY` CTE). Columns `ACCOUNT_NUMBER, RELATED_ACCOUNT_NUMBER,
RELATED_ACCOUNT_NAME, DIRECTION`. Source (UNVERIFIED table/column names, confirm with
`aix-greenlight` `describe_table`/`run_query` on a non-prod pod): `HZ_CUST_ACCT_RELATE_ALL` joined to
`HZ_CUST_ACCOUNTS` (both sides) and `HZ_PARTIES`; filters `STATUS = 'A'`, `BILL_TO_FLAG = 'Y'`,
`TRUNC(SYSDATE) BETWEEN NVL(START_DATE, …) AND NVL(END_DATE, …)`. `OUTBOUND` rows: queried account is
`CUST_ACCOUNT_ID`; `INBOUND` rows: queried account is `RELATED_CUST_ACCOUNT_ID` (`UNION ALL`).
Output XML, data-model-only (HTML fails, reference doc §3). Catalog path
`/Custom/CashApp/CashAppRelationships.xdo` → `CASHAPP_FUSION__RELATIONSHIPS_REPORT_PATH`.

**Receipt signals** (`fusion/bip/receipt_signals.sql`; consumer s12). Parameters `:P_DATE_FROM`,
`:P_DATE_TO` (`YYYY-MM-DD`, receipt date). One `G_1` row per receipt × matched statement line
(statement columns null when unreconciled):

```
CASH_RECEIPT_ID, RECEIPT_NUMBER, RECEIPT_DATE, CREATION_DATE, AMOUNT, CURRENCY_CODE,
CUSTOMER_ACCOUNT_NUMBER, RECEIPT_COMMENTS,
STATEMENT_LINE_ID, STATEMENT_LINE_REFERENCE, STATEMENT_LINE_ADDENDA, STATEMENT_PAYER_NAME,
PAYER_BANK_ACCOUNT_HASH        -- STANDARD_HASH(<bank account number>, 'SHA256'); never the raw number
```

Source tables (UNVERIFIED): `AR_CASH_RECEIPTS_ALL`, `HZ_CUST_ACCOUNTS`, `CE_STATEMENT_LINES`,
`CE_STATEMENT_HEADERS` and the reconciliation link table, `IBY_EXT_BANK_ACCOUNTS` for the payer
account. Catalog path `/Custom/CashApp/CashAppReceiptSignals.xdo` (s12 takes it as a CLI option;
no new setting).

Both SQL files are `SELECT`-only.

## Migrations

None.

## TEST PLAN (written and run only at step 5)

| AC | Test (file::name) |
|---|---|
| 1 | `test_fusion_setup_docs.py::test_setup_md_covers_every_capability` (sections for REST reads of `receivablesInvoices`, `receivablesCreditMemos`, `standardReceipts`, customer accounts; SOAP `StandardReceiptService` apply and unapply; BIP `ExternalReportWSSService` `runReport`; receipt attachments; receipt comments) |
| 1 | `test_fusion_setup_docs.py::test_every_role_row_marked_confirm_on_pod` (every row of the roles table carries "confirm on pod" or "CONFIRMED <date> <pod>") |
| 1 | `test_fusion_setup_docs.py::test_setup_md_lists_every_fusion_setting_and_vault_secret` (every `CASHAPP_FUSION__…` name from s27 `env_var_names()` appears; the password is shown as a `vault:` reference) |
| 1 | `test_fusion_setup_docs.py::test_setup_md_has_no_identifiers` (no account-like numbers, no `@` addresses; uses s43's `scan_for_identifiers` when present, else regex) |
| 2 | `test_fusion_bip_catalog.py::test_relationships_sql_filters_and_binds` (`:P_ACCOUNT_NUMBERS`, `STATUS = 'A'`, `BILL_TO_FLAG = 'Y'`, `SYSDATE` date-effective, `INBOUND` and `OUTBOUND`) |
| 2 | `test_fusion_bip_catalog.py::test_relationships_columns_match_client_parser` (XML synthesised from the SQL's column aliases parses through s05 `parse_relationships_xml` into one `CustomerRelationship`; `RELATIONSHIPS_PARAM` equals the SQL bind name) |
| 2 | `test_fusion_bip_catalog.py::test_receipt_signals_sql_shape` (both binds, every pinned column alias, `STANDARD_HASH`, no raw bank account column selected) |
| 2 | `test_fusion_bip_catalog.py::test_bip_sql_is_select_only` (no `INSERT/UPDATE/DELETE/MERGE/CREATE/ALTER/DROP/TRUNCATE/GRANT/BEGIN`) |
| 2 | `test_fusion_bip_catalog.py::test_bip_readme_has_deploy_steps_and_settings_key` (numbered steps, `/Custom/CashApp/`, `fusion.relationships_report_path` and its env var, XML output, export step) |
| 2 | `test_fusion_bip_catalog.py::test_catalog_placeholders_registered` (each of the four `*.xdmz`/`*.xdoz` either exists in `fusion/bip/catalog/` or is listed in its README as "not yet exported"); `test_report_definitions_exist` (both `*.report.md` name parameter, output XML, catalog path) |
| 3 | `test_preflight_checks.py::test_all_checks_pass_on_fake` (`FusionScenario` + `relationships_report_path` matching; every `CHECK_NAMES` present in order, no FAIL, two INFO) |
| 3 | `test_preflight_checks.py::test_rest_checks_send_rfv4_and_in_query` (`HttpFusionClient` over respx: each REST probe carries `REST-Framework-Version: 4`, `onlyData=true`, `q` with `in ('CASHAPP-PREFLIGHT-0','CASHAPP-PREFLIGHT-1')`) |
| 3 | `test_preflight_checks.py::test_rest_400_reported_as_fail` (respx 400 on the credit-memo probe → that check FAIL, detail has code/status only, others still run) |
| 3 | `test_preflight_checks.py::test_pagination_check_follows_has_more` (respx page `hasMore: true` → second GET at `offset=1`; `hasMore: false` → PASS "single page") |
| 3 | `test_preflight_checks.py::test_wsdl_checks_use_get_only` (respx: GET `?WSDL` on both services; missing operation → FAIL; XXE WSDL → FAIL) |
| 3 | `test_preflight_checks.py::test_relationships_report_requests_xml_and_expects_empty` |
| 3 | `test_preflight_checks.py::test_info_rows_show_write_enabled_and_is_production` |
| 3 | `test_preflight_checks.py::test_check_timeout_and_unexpected_error_isolated` |
| 3 | `test_preflight_cli.py::test_cli_prints_table_and_exits_0` (typer `CliRunner`, `load_settings`/`make_client` patched with `make_settings` + fake; output has header, every check name, `RESULT: PASS`) |
| 3 | `test_preflight_cli.py::test_unknown_pod_and_bad_settings_exit_2` |
| 3 | `test_preflight_cli.py::test_module_entrypoint` (`python -m cashapp.tools.preflight --help` via subprocess, exit 0) |
| 4 | `test_preflight_checks.py::test_only_read_methods_called` (run through `read_only(fake)`; all pass; `{c.method for c in fake.calls}` ⊆ `{"rest_get","get_raw","run_report"}` and disjoint from `WRITE_METHODS`) |
| 4 | `test_preflight_checks.py::test_no_write_http_requests` (`HttpFusionClient` with `write_enabled=True` via respx: only GETs plus the one BIP `runReport` POST; no PATCH/PUT/DELETE, no POST to `StandardReceiptService`) |
| 4 | `test_preflight_cli.py::test_cli_always_wraps_read_only` (`make_client` returns a fake whose write methods raise `AssertionError`; `read_only` applied, exit 0) |
| 4 | `test_preflight_checks.py::test_missing_report_fails` and `test_preflight_cli.py::test_missing_report_exit_1` (fake built with a different `relationships_report_path` → `bip.relationships_report` FAIL, other checks PASS, exit 1, `RESULT: FAIL (1 failed)`) |
| 4 | `test_preflight_checks.py::test_failure_detail_has_no_bodies_or_credentials` |
| 5 | `api/tests/live/fusion/test_preflight_live.py::test_live_preflight_dev_pod` (`@pytest.mark.live`; skipped unless settings load and the pod named by `CASHAPP_FUSION_LIVE_POD` exists with `is_production=False`; runs `run_preflight(read_only(factory.for_pod(...)))` and asserts `report.ok`, printing the table) |

## Risks

- **Role and table names.** Fusion duty/job role names, BIP folder permissions, CE/IBY table and
  column names, the relationship date columns are all from vendor knowledge. Docs say "confirm on
  pod"; SQL carries UNVERIFIED comments. The coder may confirm read-only with `aix-greenlight`
  (`describe_table`, `run_query`, `fusion_rest_describe`) on a non-production source; never
  `fusion_rest_write`, never BIP catalog upload.
- **Editing s05's package.** Adds `get_raw` to the Protocol, client, fake (and `read_only` if needed).
  s05's protocol-equality test stays green because both implementations change together. If s39
  edits the same files in the same wave, the merger resolves additive conflicts.
- **Describe endpoint shape.** `standardReceipts/describe` may be large or list children differently;
  the check looks only for a child named `attachments` (case-insensitive). If the pod lacks it, the
  check fails correctly and SETUP.md says which role grants it.
- **Full settings required.** `load_settings()` validates every group (ATP, streaming, …), so the
  preflight needs a complete env. Acceptable for onboarding; exit 2 lists missing names.
- **Probe `in (...)` against customer accounts** depends on s05's chosen resource (CRM `accounts`
  vs receivables). The check uses s05's constant, so it follows whatever s05 confirmed.
- **Pagination on an empty pod** cannot prove page 2; it passes with "single page on pod" so a fresh
  dev pod is not a false failure.
- **`receipt_applications.sql`**: if s05's live probe moved application listing to BIP (its stated
  fallback), that data model is a follow-up in `fusion/bip/`; not shipped now (no evidence yet).

## Assumptions / deviations

- `get_raw` is added to s05's `FusionClient`: AC3 needs a plain GET (`?WSDL`) that `rest_get` (JSON,
  RFV, onlyData) cannot do, and a second HTTP stack in the tool would duplicate auth/retry (DRY).
- "Attachments endpoint describable" is checked via `standardReceipts/describe` through `rest_get`
  (UNVERIFIED that `onlyData` is ignored on describe; if it breaks describe, the coder uses
  `get_raw` and parses JSON).
- "Known-empty parameter" is the sentinel account `CASHAPP-PREFLIGHT-0`; the report must return a
  well-formed `DATA_DS` with no rows.
- Exit codes: 0 pass, 1 any FAIL, 2 configuration/usage error (story names only 0/1).
- Reports live at `/Custom/CashApp/CashAppRelationships.xdo` and
  `/Custom/CashApp/CashAppReceiptSignals.xdo`; the receipt-signals path is not a setting (s12 passes
  it as an option) to avoid an s27 edit.
- The payer bank account is exposed only as a SHA-256 hash, enough for s12's equality signal and
  keeps account numbers out of the tool's inputs.
- Preflight runs against production pods too (it is read-only and wrapped); the live test is limited
  to non-production pods.
