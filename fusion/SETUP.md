# Fusion pod setup

Everything a Fusion pod needs before the cash application pipeline may run against it. Follow it
once per pod (dev, test, production), then run the preflight (last section). The pipeline must
never start against a half-configured pod.

Every role name below comes from vendor knowledge, not from a pod we have inspected. Each row is
marked **confirm on pod** until a person has checked it against the Security Console of a real
pod; replace the marker with `CONFIRMED <date> <pod>` when you do. Never guess: if a name does not
exist on the pod, find the right duty role in the Security Console and correct this file.

> **Transport (2026-10-23, fusion-mcp-transport).** REST reads and REST writes no longer use this
> integration user: they go through the fusion-sql-mcp (Greenlight) server, whose own service
> accounts need the REST read duties below (and write duties for the comment and attachment
> writes). This user is now used only for the SOAP apply and unapply (and the `?WSDL` probe).
> Register the cash app as an OAuth client of that server (scope `greenlight/mcp`) and set the
> `mcp.*` configuration keys.

## 1. Integration user

Create one dedicated integration user per pod. Do not reuse a named person's account.

- User name: a service name such as `cashapp-integration` (confirm on pod: the identity policy may
  force a naming pattern).
- Password: generated, long, never typed into chat or committed. Store it in OCI Vault (see
  section 4). Rotate it on the pod's password policy schedule.
- Password never expires: set the account so it does not lock the pipeline out at expiry (confirm
  on pod: the setting lives on the user or the password policy).
- No interactive roles (no Navigator work areas are needed): the user only calls REST, SOAP and
  BI Publisher web services.
- Data access: the user needs data access to every business unit whose receipts and invoices the
  pipeline will touch (Receivables business unit data access set; confirm on pod).

## 2. Roles per capability

Grant the smallest set that covers each capability. A custom job role built from the duty roles
below is preferred over a seeded job role. All role names are **confirm on pod**.

| Capability | What the pipeline calls | Duty or job role to grant | Status |
|---|---|---|---|
| REST read: `receivablesInvoices` | `GET receivablesInvoices` with `q=TransactionNumber in (...)` | Receivables invoice inquiry duty (for example the Accounts Receivable Specialist job role, `ORA_AR_ACCOUNTS_RECEIVABLE_SPECIALIST_JOB`) | confirm on pod |
| REST read: `receivablesCreditMemos` | `GET receivablesCreditMemos` | Same inquiry duty as invoices; credit memos are a separate resource but usually the same duty | confirm on pod |
| REST read: `standardReceipts` | `GET standardReceipts` with `expand=remittanceReferences`, `GET standardReceipts/describe` | Receipt inquiry duty (Accounts Receivable Specialist or Cash Manager receipt inquiry) | confirm on pod |
| REST read: customer accounts | `GET` of the customer account resource (path chosen in the Fusion client contracts) | Customer account inquiry duty (for example Customer Account Inquiry or the Trading Community inquiry duty) | confirm on pod |
| SOAP apply | `createApplyReceipt` on `/fscmService/StandardReceiptService` | Apply receipt duty (Accounts Receivable Specialist `Apply Receipts`) | confirm on pod |
| SOAP unapply | the unapply operation on `/fscmService/StandardReceiptService` | Unapply receipt duty (same family as apply; the operation itself is unverified) | confirm on pod |
| ~~BIP `runReport`~~ | removed 2026-10-23: the relationships and receipt-signals SQL now runs through the MCP server's `run_query` (no catalog report, no BIP role) | none for this app; the MCP server's service account needs read access to the tables the SQL reads | n/a |
| Receipt attachments | `POST standardReceipts/{id}/child/attachments` and its read | Receipt attachment duty (manage attachments on receipts) | confirm on pod |
| Receipt comments | `PATCH standardReceipts/{id}` with `Comments` | Receipt update duty (edit receipt comments) | confirm on pod |

Notes:

- Reads, applies and write-back may use different roles on a tight pod. If the preflight shows
  `FUSION_FAULT http=403` for one capability, add only the duty for that capability.
- The preflight never calls a write operation, so it cannot prove the apply, unapply, attachment
  or comment roles. Those are proven by the live write probes on a non-production pod only.

## 3. Pod-side configuration

1. Create the BI Publisher data models and reports in `fusion/bip/` (follow its README). The
   relationships report is mandatory; the receipt-signals report is optional.
2. Confirm the receipt creation-date and remittance-reference fields are exposed on
   `standardReceipts` (confirm on pod).
3. Confirm web service access is allowed from the OCI egress addresses of this system (network
   allow-list on the pod; confirm on pod).

## 4. Settings and Vault secrets per pod

Settings are environment variables loaded once at startup. A secret is never written as a value:
it is a `vault:` reference to an OCI Vault secret in `us-ashburn-1`. In the table `<POD>` is the
upper-case pod name (for example `DEV`).

| Setting | Meaning | Example form |
|---|---|---|
| `CASHAPP_FUSION__DEFAULT_POD` | pod the workers and API use | `dev` |
| `CASHAPP_FUSION__WRITE_ENABLED` | master switch for every Fusion write; `false` until a release says otherwise | `false` |
| `CASHAPP_FUSION__RELATIONSHIPS_REPORT_PATH` | catalog path of the relationships report | `/Custom/CashApp/CashAppRelationships.xdo` |
| `CASHAPP_FUSION__PODS__<POD>__BASE_URL` | pod base URL, no trailing slash | `https://<pod-host>` |
| `CASHAPP_FUSION__PODS__<POD>__USERNAME` | the integration user | `cashapp-integration` |
| `CASHAPP_FUSION__PODS__<POD>__PASSWORD` | the integration user's password, a Vault reference | `vault:ocid1.vaultsecret.oc1.iad.<secret>` |
| `CASHAPP_FUSION__PODS__<POD>__IS_PRODUCTION` | `true` only for the production pod; writes to it are refused outside prod | `false` |
| `CASHAPP_FUSION__PODS__<POD>__TESTDATA__BUSINESS_UNIT` | test-data generator business unit (non-production pods) | `<business-unit>` |
| `CASHAPP_FUSION__PODS__<POD>__TESTDATA__TRANSACTION_TYPE` | test-data transaction type | `<transaction-type>` |
| `CASHAPP_FUSION__PODS__<POD>__TESTDATA__RECEIPT_METHOD` | test-data receipt method | `<receipt-method>` |
| `CASHAPP_FUSION__PODS__<POD>__TESTDATA__BANK_ACCOUNT` | test-data bank account name | `<bank-account>` |

Vault secrets to create per pod: one secret holding the integration user's password. Create it in
the Vault of the environment, name it after the pod, and put its OCID in the `PASSWORD` setting.

## 5. Onboarding checklist

1. [ ] Integration user created, password in Vault, never expires.
2. [ ] Roles in section 2 granted; each row's marker updated to `CONFIRMED <date> <pod>`.
3. [ ] Data access set for the receivables business units.
4. [ ] BI Publisher data models and reports deployed from `fusion/bip/` and catalog exports
       committed to `fusion/bip/catalog/`.
5. [ ] Settings in section 4 added for the pod; `IS_PRODUCTION` set correctly; `WRITE_ENABLED`
       left `false`.
6. [ ] Run the preflight and fix every FAIL row:

       uv run python -m cashapp.tools.preflight --pod <name>

   It is read-only and safe on any pod. Exit code 0 means every check passed, 1 means at least
   one failed, 2 means the settings or the pod name are wrong. Do not enable the pod for the
   pipeline until it exits 0.
