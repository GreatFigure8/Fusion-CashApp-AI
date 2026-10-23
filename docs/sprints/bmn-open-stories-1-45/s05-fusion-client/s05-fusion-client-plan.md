# Plan: s05-fusion-client

Issue #5. Wave 1 adapter (story file says wave 2; it owns `cashapp/integrations/fusion/`). Paths:
`cashapp/` = `api/src/cashapp/`. Follows research.md a3 (httpx + defusedxml, custom fail-closed SOAP
parsing) and the a6 rails (writes off by default, prod-pod refusal, defusedxml). Reference doc §3 is
the source for every call, header, fault and noise code.

## Standards followed

- CLAUDE.md *Fusion integration*: one `FusionClient`; `REST-Framework-Version: 4`; `onlyData=true`;
  explicit `fields=`; `hasMore` pagination; `q=` escaping; batched `in (...)` lookups on both
  `receivablesInvoices` and `receivablesCreditMemos`; SOAP `createApplyReceipt` keyed on IDs, signed
  amounts, accounting date = later of payment date and today; fail-closed parsing; never OIC.
- CLAUDE.md *Conventions*: money is `Decimal` via `cashapp.domain.money.to_money` (JSON parsed with
  `parse_float=Decimal`, never through `float`); remittance content and request bodies are never
  logged; only Fusion codes, HTTP status, method, pod name, attempt and latency reach logs/spans.
- "Never guess an endpoint, payload or field name": every name not yet confirmed on a non-prod pod
  carries an `# UNVERIFIED:` comment in code and a row in `CONTRACTS.md`; the `-m live` probes
  confirm them.
- research.md: exactly two implementations behind the interface (`HttpFusionClient`,
  `FakeFusionClient`). The fake is never presented as a confirmed contract.
- `python-web-app:building-python-web-apps`: the SDK/HTTP surface is isolated in one integration
  package; services receive the client as an argument. Settings are injected, never read globally
  inside the client (only `factory.build_fusion_client` touches `Settings`).
- pyright strict, ruff. Models are frozen, slotted dataclasses (story AC1), not Pydantic. No
  SQLAlchemy import (layering test from s02).

## Files to touch

All new, all owned by this story (file-disjoint from every other story).

| Path | Contents |
|---|---|
| `api/src/cashapp/integrations/fusion/__init__.py` | re-exports the public names below (`FusionClient`, models, `FusionError`, `FusionFault`, `accounting_date_for`, `q_literal`, `FusionClientFactory`, `build_fusion_client`, `read_only`, `WriteGuard`) |
| `api/src/cashapp/integrations/fusion/models.py` | frozen dataclasses: transactions, receipts, applications, customers, relationships, apply/unapply requests and results, `FusionMessage`, `AttachmentRef` |
| `api/src/cashapp/integrations/fusion/errors.py` | `FusionError`, `FusionFault`, `NOISE_CODES`, `FUSION_CODE_MAP`, `classify_fusion_code`, `fault_from_messages`, `error_from_http` |
| `api/src/cashapp/integrations/fusion/query.py` | `q_literal`, `q_in`, `chunked`, `REST_BASE`, `FIELDS_*` constants (one per resource) |
| `api/src/cashapp/integrations/fusion/transport.py` | `FusionTransport`: httpx `AsyncClient`, basic auth, headers, retry/backoff, `span("fusion.<method>")`, `get_json_paged`, `post_json`, `patch_json`, `post_soap` |
| `api/src/cashapp/integrations/fusion/soap.py` | `accounting_date_for`, `build_apply_envelope`, `build_unapply_envelope`, `parse_apply_response`, `parse_unapply_response`, `SOAP_PATH_RECEIPTS` |
| `api/src/cashapp/integrations/fusion/bip.py` | `build_run_report_envelope`, `parse_run_report_response`, `parse_relationships_xml`, `BIP_PATH`, `RELATIONSHIPS_PARAM` |
| `api/src/cashapp/integrations/fusion/guard.py` | `WriteGuard`, `read_only(client)`, `WRITE_METHODS` |
| `api/src/cashapp/integrations/fusion/client.py` | `FusionClient` Protocol, `HttpFusionClient`, `FusionClientOptions` |
| `api/src/cashapp/integrations/fusion/factory.py` | `FusionClientFactory`, `build_fusion_client(settings)` (s30 imports it by path) |
| `api/src/cashapp/integrations/fusion/fake.py` | `FakeFusionClient` (in-memory ledger, Fusion behaviour, recorded calls, fault injection, s23 REST POST surface) |
| `api/src/cashapp/integrations/fusion/CONTRACTS.md` | one row per endpoint/field/element: status `UNVERIFIED` / `CONFIRMED <date> <pod>`, source |
| `api/tests/support/fusion.py` | `FusionScenario` builder + `load_scenario(path)`; pytest fixtures `fusion_scenario`, `fake_fusion` |
| `api/tests/fixtures/fusion/rest/*.json` | recorded-shape REST pages: `invoices_page1.json` (`hasMore: true`), `invoices_page2.json`, `credit_memos.json`, `receipts_expand_refs.json`, `receipts_created_since.json`, `customer_account.json`, `error_400_rfv.json` |
| `api/tests/fixtures/fusion/soap/*.xml` | `apply_success.xml`, `apply_fault_http200.xml` (ADF `ServiceErrorMessage` in 200), `apply_noise_mixed.xml` (8 messages, noise around one AR-855287), `apply_noise_only_no_value.xml`, `apply_soap_fault_500.xml` (AR-856102), `apply_lock.xml` (ORA-00054), `apply_gl_date.xml` (AR-856089), `apply_xxe.xml` (DOCTYPE/entity), `bip_run_report_response.xml`, `bip_relationships_data.xml` |
| `api/tests/fixtures/fusion/scenarios/basic.json` | a `FusionScenario` JSON (shape pinned below) |
| `api/tests/unit/fusion/test_fusion_query.py` | AC2 escaping/chunking |
| `api/tests/unit/fusion/test_fusion_rest_client.py` | AC1/AC2 REST methods via `respx` |
| `api/tests/unit/fusion/test_fusion_soap.py` | AC3 |
| `api/tests/unit/fusion/test_fusion_bip.py` | AC1 `run_report`, relationships |
| `api/tests/unit/fusion/test_fusion_errors.py` | AC4 |
| `api/tests/unit/fusion/test_fusion_guard_factory.py` | AC5 |
| `api/tests/unit/fusion/test_fusion_fake.py` | AC6 |
| `api/tests/live/fusion/test_fusion_live.py` | AC7 (`@pytest.mark.live`) |

No `pyproject.toml`/lockfile edits: `httpx`, `defusedxml`, `respx`, `time-machine` are pinned by s01.
No settings edits: `fusion.relationships_report_path` already exists in s27's pinned model. Test
directories get no `__init__.py` unless s01's layout uses them; test file basenames are prefixed
`test_fusion_` so they cannot collide.

## Design

### Transport and retry (`transport.py`)

- One `httpx.AsyncClient(base_url=pod.base_url, auth=BasicAuth(username, password.get_secret_value()),
  timeout=options.timeout_s)`. An injectable `transport: httpx.AsyncBaseTransport | None` lets tests
  use `respx`/`MockTransport`. An injectable `sleep: Callable[[float], Awaitable[None]]` makes backoff
  testable without waiting.
- Every REST GET: headers `REST-Framework-Version: 4`, `Accept: application/json`; params always
  include `onlyData=true`, `fields=<explicit list>`, `limit=options.page_size`, `offset`. A call
  without `fields` is a programming error (`ValueError`), enforced in `get_json_paged`.
- Pagination: loop while `hasMore` is true, `offset += len(items)`; stops on an empty page even if
  `hasMore` lies (guard against infinite loops), and caps at `options.max_pages` (raise
  `FusionError(FUSION_FAULT)` if exceeded).
- Responses parsed with `json.loads(resp.content, parse_float=Decimal)`; money fields pass through
  `to_money`.
- **Retry policy (bounded, max 3 attempts total, exponential backoff `base * 2**n` with full jitter,
  capped at `backoff_max_s`):**
  - Reads (`GET`, BIP `runReport`): retry on any `FUSION_TRANSIENT` (connect/read/pool timeouts,
    network errors, 401, 5xx, 404 whose body contains `NotAuthorizedOrNotFound`).
  - Writes (`createApplyReceipt`, unapply, comment PATCH, attachment POST, `rest_post`): retry **only
    when Fusion certainly did not process the request**: `ConnectError`, `ConnectTimeout`,
    `PoolTimeout`, 401, 503. A `ReadTimeout`, 500 without a parseable SOAP fault, 502 or 504 on a
    write raises `FusionError(FUSION_TRANSIENT, outcome_unknown=True)` immediately, so the caller
    (s15) reconciles with `list_receipt_applications` before any re-apply. (Deviation, see
    Assumptions.)
  - SOAP: an HTTP 500 carrying a parseable `Fault` envelope is a business fault, parsed into
    `FusionFault`, never treated as transient.
- Each call is wrapped in `span(f"fusion.{method}", pod=..., attempt=...)` and logs one line at INFO
  (`method`, `pod`, `status`, `attempts`, `latency_ms`, `fusion_code`). No URL query string (it holds
  transaction numbers), no body, no credentials.

### Queries (`query.py`)

- `q_literal(value: str) -> str` returns `'` + value with every `'` doubled + `'`. Rejects control
  characters (`ValueError`). `q_in(field, values)` returns `field in ('a','b')` built only from
  `q_literal`. Dates render as `'YYYY-MM-DD'`; datetimes as `'YYYY-MM-DDTHH:MM:SS+00:00'`
  (UNVERIFIED format for `CreationDate`).
- `chunked(values, size=50)` deduplicates (order kept) before chunking.

### REST calls (all under `REST_BASE = "/fscmRestApi/resources/11.13.18.05"`)

| Method | Call |
|---|---|
| `find_transactions` | per chunk of 50: `GET receivablesInvoices?q=TransactionNumber in (...)` and `GET receivablesCreditMemos?q=TransactionNumber in (...)`, run concurrently. Invoice fields: `CustomerTransactionId, TransactionNumber, InvoiceBalanceAmount, EnteredAmount*, BillToCustomerNumber, BillToSite*, BusinessUnit, InvoiceCurrencyCode, InvoiceStatus, PaymentTerms*`. Credit memo fields: `CustomerTransactionId, TransactionNumber, TransactionBalanceDue, EnteredAmount*, BillToCustomerNumber, BillToSite*, BusinessUnit, CurrencyCode*, TransactionStatus*`. Credit memo `balance = -abs(raw)`, `original_amount = -abs(raw)`. Same number found as both kinds: both returned. |
| `find_receipts` | per chunk of customer numbers: `GET standardReceipts?q=CustomerAccountNumber in (...) AND ReceiptDate BETWEEN 'd1' AND 'd2'` (or `CreationDate BETWEEN` for `by="creation_date"`) `&expand=remittanceReferences`. Fields: `StandardReceiptId, ReceiptNumber, Amount, UnappliedAmount, Currency, CustomerAccountNumber, ReceiptDate, CreationDate*, Status, State, Comments*`; child `remittanceReferences` field `ReferenceNumber*`. No amount/currency/status filter (tenant can't). |
| `receipts_created_since` | `GET standardReceipts?q=CreationDate >= '<iso>'&orderBy=CreationDate:asc,StandardReceiptId:asc&expand=remittanceReferences`, paged until `limit` items. Inclusive `>=`: the caller (s14) dedupes on `receipt_id` at the high-water mark. |
| `get_receipt` | `GET standardReceipts/{id}?expand=remittanceReferences`. |
| `list_receipt_applications` | `GET standardReceipts/{id}/child/receiptApplications*` (UNVERIFIED resource). If the live probe shows no such child, the coder switches to a BIP data model (`receipt_applications.sql`, recorded as a request to s32) without changing the method signature. |
| `list_transaction_applications` | `GET receivablesInvoices/{customer_trx_id}/child/...*` (UNVERIFIED, same fallback). |
| `get_customer_account` | `GET /crmRestApi/resources/11.13.18.05/accounts?q=AccountNumber=...*` or the receivables customer-account resource (UNVERIFIED; the coder confirms with `aix-greenlight` `fusion_rest_describe`). `currency_codes` from the account's site/profile currencies plus the currencies of its open transactions if the profile has none (UNVERIFIED). |
| `set_receipt_comment` | `PATCH standardReceipts/{id}` body `{"Comments": text}` (UNVERIFIED, s17 confirms field and size). |
| `attach_to_receipt` | `POST standardReceipts/{id}/child/attachments` body `{"DatatypeCode":"FILE","FileName","Title","UploadedFileContentType","FileContents": base64}` (UNVERIFIED, s17). |

`*` = UNVERIFIED in `CONTRACTS.md`.

### SOAP apply/unapply (`soap.py`)

- `POST /fscmService/StandardReceiptService`, `Content-Type: text/xml; charset=utf-8`,
  `SOAPAction` per WSDL (UNVERIFIED). Envelopes built with `xml.etree.ElementTree` (values are
  escaped by the serializer, never f-strings). Request elements: `ReceiptId`, `CustomerTrxId`,
  `AmountApplied` (signed, `f"{d:.2f}"`), `ReceiptCurrency`* , `ApplicationDate`, `AccountingDate`,
  and `DiscountTaken`* only when `discount_amount` is not None.
- `accounting_date_for(payment_date, today) = max(payment_date, today)`; `HttpFusionClient` fills
  `ApplyRequest.application_date`/`accounting_date` only through the caller, but s15 must call this
  helper (one implementation).
- **Fail-closed parse** (`parse_apply_response(xml: bytes, *, receipt_id) -> ApplyResult`):
  1. `defusedxml.ElementTree.fromstring`; any parse error, DTD or entity → `ok=False`,
     fault `FUSION_FAULT` ("unparseable response").
  2. Collect every message from `Fault/faultstring`, `Fault/detail//ServiceErrorMessage` and nested
     `ServiceMessage`/`detail` items as `FusionMessage(code, severity, text)` (namespace-agnostic
     local-name matching). Codes come from the `code` element, else the first `AR-\d{6}` /
     `ORA-\d{5}` / `[A-Z_]{6,}` token in the text.
  3. Drop `NOISE_CODES` (`AR_RAPI_TRX_NUM_IGN`, `AR_RAPI_RCPT_NUM_IGN`, `GENERIC_MESSAGE`,
     `FND_AS_UNEXPECTED_ERROR`, `AR-855741`, `AR-855799`).
  4. Any remaining message → `ok=False`, fault = `fault_from_messages(remaining)`: the first message
     whose code is in `FUSION_CODE_MAP` by precedence OVERAPPLY > ALREADY_APPLIED > GL_DATE > LOCKED,
     else the first remaining message as `FUSION_FAULT`.
  5. No remaining message: `ok=True` only if a `Value` element exists; otherwise `ok=False`,
     `FUSION_FAULT` ("no Value block").
  6. `application_id` from `Value//ReceivableApplicationId`* (None if absent; not a failure).
     The matched `receipt_id` is kept by the caller's request; the response's nil `ReceiptId` is
     ignored. `raw_messages` holds every message, noise included, for history.

### BIP (`bip.py`)

- `POST /xmlpserver/services/ExternalReportWSSService` operation `runReport`:
  `reportRequest{reportAbsolutePath, attributeFormat=fmt, sizeOfDataChunkDownload=-1,
  parameterNameValues{item{name, values{item}}}}`; response `reportBytes` Base64-decoded. Auth:
  HTTP basic (same pod credentials; UNVERIFIED that WSS needs no UsernameToken). A SOAP fault →
  `FusionError(FUSION_FAULT)`; transient rules as reads.
- `customer_relationships(account_numbers)` runs `run_report(settings.fusion.relationships_report_path,
  {RELATIONSHIPS_PARAM: ",".join(chunk)})` per chunk of 50 and parses the pinned row shape below,
  then deduplicates INBOUND/OUTBOUND into one `CustomerRelationship` per (queried account, related
  account) with the directions seen. Self-relationships are dropped.

### Write rails (`guard.py`)

- `WriteGuard(write_enabled: bool, env: Env, pod_name: str, pod_is_production: bool)`;
  `check(method: str) -> None` raises `FusionError(FUSION_WRITE_DISABLED, retryable=False)` when
  `not write_enabled`, or when `pod_is_production and env != "prod"`. Called first in every write
  method, before any I/O, in both `HttpFusionClient` and `FakeFusionClient` (one implementation).
- `read_only(client) -> FusionClient` returns a wrapper whose write methods (`WRITE_METHODS`) always
  raise `FusionError(FUSION_WRITE_DISABLED)` and whose reads delegate. Provided once here for s12
  and s32 (both need "a wrapper that raises on any write").

## Interfaces provided (pinned)

```python
# cashapp/integrations/fusion/models.py   (all: @dataclass(frozen=True, slots=True); money is Decimal via to_money)
class TransactionKind(StrEnum): INVOICE = "INVOICE"; CREDIT_MEMO = "CREDIT_MEMO"

class FusionTransaction:
    customer_trx_id: int; number: str; kind: TransactionKind
    balance: Decimal                 # credit memos negative
    original_amount: Decimal         # credit memos negative
    currency: str; status: str
    bill_to_customer_number: str | None; bill_to_site: str | None
    business_unit: str | None; payment_terms: str | None

class FusionReceipt:
    receipt_id: int; receipt_number: str; amount: Decimal; unapplied_amount: Decimal
    currency: str; customer_account_number: str | None
    receipt_date: date; creation_date: datetime        # tz-aware UTC
    status: str; state: str
    remittance_references: tuple[str, ...] = (); comments: str | None = None

class FusionApplication:
    application_id: int; receipt_id: int; customer_trx_id: int
    amount_applied: Decimal; apply_date: date; status: str      # e.g. "APP"; reversed ones kept with their status

class FusionCustomerSite:
    site_number: str; purpose: str | None; location: str | None; address: str | None

class FusionCustomer:
    account_number: str; name: str; currency_codes: tuple[str, ...]; sites: tuple[FusionCustomerSite, ...]

RelationshipDirection = Literal["INBOUND", "OUTBOUND"]
class CustomerRelationship:
    account_number: str              # the queried account
    related_account_number: str
    related_account_name: str | None
    directions: frozenset[RelationshipDirection]

class FusionMessage:
    code: str | None; severity: str | None; text: str

class ApplyRequest:
    receipt_id: int; customer_trx_id: int
    amount_applied: Decimal          # signed: negative for credit memos
    receipt_currency: str; application_date: date; accounting_date: date
    discount_amount: Decimal | None = None      # s39

class ApplyResult:
    ok: bool; application_id: int | None; fault: FusionFault | None
    raw_messages: tuple[FusionMessage, ...]
    receipt_id: int                  # the id matched on (response ReceiptId is nil)

class UnapplyRequest:
    receipt_id: int; application_id: int; reversal_gl_date: date; reason: str

class UnapplyResult:
    ok: bool; fault: FusionFault | None; raw_messages: tuple[FusionMessage, ...]

class AttachmentRef:
    receipt_id: int; attachment_id: str | None; filename: str

# cashapp/integrations/fusion/errors.py
NOISE_CODES: frozenset[str]
FUSION_CODE_MAP: Mapping[str, ErrorCode]   # AR-855287→FUSION_OVERAPPLY, AR-856102→FUSION_ALREADY_APPLIED,
                                           # ORA-00054, AR-856792→FUSION_LOCKED, AR-856089→FUSION_GL_DATE
@dataclass(frozen=True, slots=True)
class FusionFault:
    code: ErrorCode; fusion_code: str | None; message: str; messages: tuple[FusionMessage, ...]

class FusionError(Exception):
    def __init__(self, code: ErrorCode, message: str, *, fusion_code: str | None = None,
                 retryable: bool | None = None,          # default: code.spec.retryable
                 http_status: int | None = None, outcome_unknown: bool = False) -> None
    code: ErrorCode; fusion_code: str | None; message: str; retryable: bool
    http_status: int | None; outcome_unknown: bool
    @classmethod
    def from_fault(cls, fault: FusionFault) -> FusionError

def classify_fusion_code(fusion_code: str | None) -> ErrorCode          # unknown/None → FUSION_FAULT
def fault_from_messages(messages: Sequence[FusionMessage]) -> FusionFault | None   # noise removed; None if nothing left
def error_from_http(status: int, body: bytes | None) -> FusionError      # 401/5xx/404 NotAuthorizedOrNotFound → FUSION_TRANSIENT

# cashapp/integrations/fusion/query.py
REST_BASE = "/fscmRestApi/resources/11.13.18.05"
def q_literal(value: str) -> str
def q_in(field: str, values: Sequence[str]) -> str
def chunked(values: Iterable[str], size: int = 50) -> list[list[str]]

# cashapp/integrations/fusion/soap.py
def accounting_date_for(payment_date: date, today: date) -> date      # max(payment_date, today)
def parse_apply_response(xml: bytes, *, receipt_id: int) -> ApplyResult

# cashapp/integrations/fusion/client.py
ReceiptDateBasis = Literal["receipt_date", "creation_date"]

class FusionClient(Protocol):
    pod_name: str
    async def find_transactions(self, numbers: Sequence[str]) -> list[FusionTransaction]: ...
    async def find_receipts(self, *, customer_numbers: Sequence[str], date_from: date, date_to: date,
                            by: ReceiptDateBasis = "receipt_date") -> list[FusionReceipt]: ...
    async def receipts_created_since(self, since: datetime, *, limit: int = 500) -> list[FusionReceipt]: ...
    async def get_receipt(self, receipt_id: int) -> FusionReceipt: ...
    async def list_receipt_applications(self, receipt_id: int) -> list[FusionApplication]: ...
    async def list_transaction_applications(self, customer_trx_id: int) -> list[FusionApplication]: ...
    async def get_customer_account(self, account_number: str) -> FusionCustomer: ...   # not found → FusionError(CUSTOMER_NOT_FOUND)
    async def customer_relationships(self, account_numbers: Sequence[str]) -> list[CustomerRelationship]: ...
    async def apply_receipt(self, request: ApplyRequest) -> ApplyResult: ...           # business faults in result; transport/guard → FusionError
    async def unapply_receipt(self, request: UnapplyRequest) -> UnapplyResult: ...     # UNVERIFIED (s38)
    async def set_receipt_comment(self, receipt_id: int, text: str) -> None: ...       # UNVERIFIED (s17)
    async def attach_to_receipt(self, receipt_id: int, filename: str, content: bytes,
                                content_type: str, title: str) -> AttachmentRef: ...   # UNVERIFIED (s17)
    async def run_report(self, path: str, params: Mapping[str, str], fmt: str = "xml") -> bytes: ...
    async def rest_get(self, path: str, params: Mapping[str, str] | None = None) -> dict[str, Any]: ...
        # path relative to REST_BASE unless it starts with "/"; adds the RFV header and onlyData; single page
    async def rest_post(self, path: str, json: Mapping[str, Any]) -> dict[str, Any]: ...  # guarded write
    async def aclose(self) -> None: ...

@dataclass(frozen=True, slots=True)
class FusionClientOptions:
    timeout_s: float = 60.0; page_size: int = 500; chunk_size: int = 50; max_pages: int = 200
    max_attempts: int = 3; backoff_base_s: float = 0.5; backoff_max_s: float = 8.0

class HttpFusionClient:          # implements FusionClient; also an async context manager
    def __init__(self, *, pod_name: str, pod: FusionPodSettings, guard: WriteGuard,
                 relationships_report_path: str, options: FusionClientOptions = FusionClientOptions(),
                 transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None

# cashapp/integrations/fusion/guard.py
WRITE_METHODS: frozenset[str]    # apply_receipt, unapply_receipt, set_receipt_comment, attach_to_receipt, rest_post
class WriteGuard:
    def __init__(self, *, write_enabled: bool, env: str, pod_name: str, pod_is_production: bool) -> None
    @classmethod
    def from_settings(cls, settings: Settings, pod_name: str) -> WriteGuard
    @classmethod
    def allow_all(cls) -> WriteGuard                     # tests and the fake's default
    def check(self, method: str) -> None                 # raises FusionError(FUSION_WRITE_DISABLED)
def read_only(client: FusionClient) -> FusionClient

# cashapp/integrations/fusion/factory.py
class FusionClientFactory:
    def __init__(self, settings: Settings, *, options: FusionClientOptions = FusionClientOptions(),
                 transport: httpx.AsyncBaseTransport | None = None) -> None
    def for_pod(self, name: str | None = None) -> HttpFusionClient   # None → settings.fusion.default_pod;
                                                                      # unknown name → KeyError naming known pods
def build_fusion_client(settings: Settings) -> FusionClient           # s30 container: for_pod(default); s30 calls aclose() on shutdown

# cashapp/integrations/fusion/fake.py
@dataclass(frozen=True, slots=True)
class FakeCall: method: str; args: tuple[Any, ...]; kwargs: Mapping[str, Any]

class FakeFusionClient:          # implements FusionClient
    pod_name: str = "fake"
    calls: list[FakeCall]
    def __init__(self, *, transactions=(), receipts=(), applications=(), customers=(),
                 relationships=(), reports: Mapping[str, bytes] | None = None,
                 guard: WriteGuard | None = None,          # default WriteGuard.allow_all()
                 relationships_report_path: str = "/Custom/CashApp/Relationships.xdo",
                 today: Callable[[], date] | None = None) -> None
    @classmethod
    def from_json(cls, data: Mapping[str, Any] | str | Path, **kwargs: Any) -> FakeFusionClient
    def fail_next(self, method: str, error: FusionError | FusionFault, *, times: int = 1) -> None
        # FusionError is raised; FusionFault is returned in ApplyResult/UnapplyResult
    # ledger read-back for assertions:
    def transaction(self, number: str, kind: TransactionKind | None = None) -> FusionTransaction
    def receipt(self, receipt_id: int) -> FusionReceipt
    def applications(self, *, receipt_id: int | None = None, customer_trx_id: int | None = None) -> list[FusionApplication]
    def comments(self, receipt_id: int) -> str | None
    def attachments(self, receipt_id: int) -> list[AttachmentRef]
    def posted(self, path: str) -> list[dict[str, Any]]   # bodies sent via rest_post (s23)
```

**Fake behaviour (pinned):**
- `apply_receipt`: unknown receipt/transaction → fault `FUSION_FAULT`; currency differs from receipt →
  `FUSION_FAULT`; an active application of this receipt to this transaction exists → fault
  `FUSION_ALREADY_APPLIED` (`AR-856102`); `abs(amount)` greater than `abs(balance)` (sign-aware for
  credit memos) or than receipt unapplied (for positive amounts) → fault `FUSION_OVERAPPLY`
  (`AR-855287`); `accounting_date` before the receipt date → `FUSION_GL_DATE` (`AR-856089`).
  Success decrements `balance` and receipt `unapplied_amount`, adds a `FusionApplication`
  (sequential ids from 900001), and returns `application_id`.
- `unapply_receipt` reverses: restores balance and unapplied, marks the application `status="REVERSED"`.
- `rest_post` supports s23's paths: `receivablesInvoices`, `receivablesInvoices/{id}/action/completeTransaction`,
  `receivablesCreditMemos`, `standardReceipts` (creates ledger rows from the POSTed body using the
  same UNVERIFIED field names as the REST fields above); any other path → `FusionError(FUSION_FAULT, http_status=404)`.
- `rest_get(path)` serves `receivablesInvoices`, `receivablesCreditMemos`, `standardReceipts` lists
  (no `q` evaluation beyond `TransactionNumber`/`ReceiptNumber` `=`/`in`), enough for s23 read-back and s32.
- `run_report(path)` returns `reports[path]`; the relationships path is rendered from `relationships`;
  unknown path → `FusionError(FUSION_FAULT)` (s32's "missing report" case).
- Every method appends a `FakeCall`; every write method calls `guard.check` first.

### Relationships report row shape (pinned for s32's `fusion/bip/relationships.sql`)

Parameter `RELATIONSHIPS_PARAM = "P_ACCOUNT_NUMBERS"` (comma-separated account numbers). Output:

```xml
<DATA_DS><G_1>
  <ACCOUNT_NUMBER>1001</ACCOUNT_NUMBER><RELATED_ACCOUNT_NUMBER>2002</RELATED_ACCOUNT_NUMBER>
  <RELATED_ACCOUNT_NAME>…</RELATED_ACCOUNT_NAME><DIRECTION>INBOUND|OUTBOUND</DIRECTION>
</G_1>…</DATA_DS>
```

### `FusionScenario` (pinned; `api/tests/support/fusion.py`, JSON shape for s43 and s24)

```python
class FusionScenario:
    def customer(self, account_number: str, *, name: str = ..., currencies: Sequence[str] = ("USD",),
                 sites: Sequence[FusionCustomerSite] = ()) -> Self
    def invoice(self, number: str, amount: str | Decimal, *, customer: str, currency: str = "USD",
                balance: str | Decimal | None = None, status: str = "Open", terms: str | None = None,
                business_unit: str = "BU1", bill_to_site: str | None = None) -> Self
    def credit_memo(self, number: str, amount: str | Decimal, *, customer: str, currency: str = "USD",
                    balance: str | Decimal | None = None, status: str = "Open") -> Self   # stored negative
    def receipt(self, number: str, amount: str | Decimal, *, customer: str | None, receipt_date: date,
                currency: str = "USD", unapplied: str | Decimal | None = None,
                creation_date: datetime | None = None,      # default receipt_date 00:00 UTC
                references: Sequence[str] = (), status: str = "UNAPP", state: str = "CLEARED",
                comments: str | None = None) -> Self
    def application(self, receipt_number: str, transaction_number: str, amount: str | Decimal,
                    *, apply_date: date | None = None) -> Self   # adjusts balances as Fusion would
    def relationship(self, account: str, related: str, *, name: str | None = None) -> Self   # both directions
    def report(self, path: str, content: bytes) -> Self
    def to_json(self) -> dict[str, Any]
    def build(self, *, guard: WriteGuard | None = None, today: date | None = None) -> FakeFusionClient

def load_scenario(path: str | Path) -> FusionScenario
@pytest.fixture
def fusion_scenario() -> FusionScenario
```

IDs are assigned deterministically (transactions from 100001, receipts from 500001). JSON shape
(`to_json` / `FakeFusionClient.from_json`), money as strings, dates ISO 8601:

```json
{"customers": [{"account_number": "1001", "name": "Customer A", "currency_codes": ["USD"], "sites": []}],
 "transactions": [{"customer_trx_id": 100001, "number": "INV-1", "kind": "INVOICE", "balance": "100.00",
   "original_amount": "100.00", "currency": "USD", "status": "Open", "bill_to_customer_number": "1001",
   "bill_to_site": null, "business_unit": "BU1", "payment_terms": null}],
 "receipts": [{"receipt_id": 500001, "receipt_number": "R-1", "amount": "100.00", "unapplied_amount": "100.00",
   "currency": "USD", "customer_account_number": "1001", "receipt_date": "2026-01-05",
   "creation_date": "2026-01-06T09:00:00+00:00", "status": "UNAPP", "state": "CLEARED",
   "remittance_references": [], "comments": null}],
 "applications": [{"application_id": 900001, "receipt_id": 500001, "customer_trx_id": 100001,
   "amount_applied": "40.00", "apply_date": "2026-01-06", "status": "APP"}],
 "relationships": [{"account_number": "1001", "related_account_number": "2002", "related_account_name": null}],
 "reports": {}}
```

## Migrations

None.

## TEST PLAN (written and run only at step 5)

| AC | Test (file::name) |
|---|---|
| 1 | `test_fusion_rest_client.py::test_find_transactions_queries_invoices_and_credit_memos_in_one_batch` (respx: exactly one call per resource for ≤50 numbers; both `TransactionNumber in (...)`) |
| 1 | `test_fusion_rest_client.py::test_find_transactions_chunks_at_50_and_dedupes` (120 numbers with repeats → 3 chunks per resource) |
| 1 | `test_fusion_rest_client.py::test_credit_memo_balance_is_negative_and_money_is_decimal` (no `float` anywhere in the models) |
| 1 | `test_fusion_rest_client.py::test_find_receipts_by_receipt_date_and_creation_date` (`ReceiptDate BETWEEN` vs `CreationDate BETWEEN`, `expand=remittanceReferences`, references mapped, no amount/currency filter in `q`) |
| 1 | `test_fusion_rest_client.py::test_receipts_created_since_orders_by_creation_and_honours_limit` |
| 1 | `test_fusion_rest_client.py::test_get_receipt_and_applications_map_fields` |
| 1 | `test_fusion_rest_client.py::test_get_customer_account_maps_sites_and_currencies_and_not_found` |
| 1 | `test_fusion_rest_client.py::test_set_comment_and_attach_send_expected_bodies` (base64 `FileContents`) |
| 1 | `test_fusion_rest_client.py::test_rest_get_and_rest_post_low_level` |
| 1 | `test_fusion_bip.py::test_run_report_builds_request_and_base64_decodes` |
| 1 | `test_fusion_bip.py::test_customer_relationships_dedupes_inbound_outbound_and_drops_self` (uses `relationships_report_path` from settings) |
| 1 | `test_fusion_soap.py::test_unapply_success_and_fault` |
| 2 | `test_fusion_rest_client.py::test_every_rest_call_sends_rfv4_onlydata_and_fields` (respx route asserting on all recorded requests of the module's other tests via a shared fixture) |
| 2 | `test_fusion_rest_client.py::test_has_more_pagination_follows_offset` (page1 `hasMore: true` → page2) |
| 2 | `test_fusion_rest_client.py::test_pagination_stops_on_empty_page_and_caps_pages` |
| 2 | `test_fusion_query.py::test_q_literal_doubles_single_quotes` (`O'Brien` → `'O''Brien'`) |
| 2 | `test_fusion_query.py::test_q_in_escapes_every_value` (`in ('A''1','B')`) |
| 2 | `test_fusion_query.py::test_q_literal_rejects_control_characters` |
| 2 | `test_fusion_query.py::test_only_q_literal_builds_literals` (static: no `"'"` string formatting of `q=` values elsewhere in the package) |
| 3 | `test_fusion_soap.py::test_apply_envelope_keys_on_ids_signed_amount_and_dates` (`ReceiptId`, `CustomerTrxId`, `-25.00` for a credit memo, no `DiscountTaken` when None; values XML-escaped) |
| 3 | `test_fusion_soap.py::test_accounting_date_for_takes_later_date` (past, today, future) |
| 3 | `test_fusion_soap.py::test_success_requires_value_block` (`apply_success.xml` → ok, `application_id`, `receipt_id` = matched id despite nil) |
| 3 | `test_fusion_soap.py::test_service_error_inside_http_200_is_failure` (`apply_fault_http200.xml`) |
| 3 | `test_fusion_soap.py::test_noise_codes_ignored_real_fault_found_in_middle` (`apply_noise_mixed.xml` → `FUSION_OVERAPPLY`, all 8 messages in `raw_messages`) |
| 3 | `test_fusion_soap.py::test_noise_only_without_value_fails_closed` |
| 3 | `test_fusion_soap.py::test_soap_fault_in_http_500_is_business_fault_not_transient` (no retry) |
| 3 | `test_fusion_soap.py::test_malformed_and_xxe_responses_fail_closed` (defusedxml) |
| 4 | `test_fusion_errors.py::test_fusion_code_mapping` (parametrised: AR-855287, AR-856102, ORA-00054, AR-856792, AR-856089, unknown → FUSION_FAULT; `retryable` from `ErrorCode.spec`) |
| 4 | `test_fusion_errors.py::test_http_errors_map_to_transient` (401, 500, 502, 503, 504, 404 `NotAuthorizedOrNotFound`, timeouts; plain 404 → FUSION_FAULT) |
| 4 | `test_fusion_errors.py::test_reads_retry_transient_three_times_with_backoff` (fake `sleep` records growing, capped delays; third failure raises `FUSION_TRANSIENT`; second-attempt success returns) |
| 4 | `test_fusion_errors.py::test_writes_retry_only_when_not_processed` (ConnectError/503 retried; ReadTimeout/502 raise at once with `outcome_unknown=True`) |
| 4 | `test_fusion_errors.py::test_logs_and_spans_carry_no_bodies_or_credentials` (`capture_logs`/`capture_spans` from s29: no transaction numbers, password or envelope text) |
| 5 | `test_fusion_guard_factory.py::test_factory_selects_pod_by_name_and_default` (`make_settings` with pods dev/test; unknown → KeyError; credentials from `SecretStr`) |
| 5 | `test_fusion_guard_factory.py::test_every_write_method_refused_when_write_disabled` (parametrised over `WRITE_METHODS`, respx asserts zero requests) |
| 5 | `test_fusion_guard_factory.py::test_production_pod_refused_outside_prod_env` (env dev + `is_production=True` → refused even with writes enabled; env prod → allowed) |
| 5 | `test_fusion_guard_factory.py::test_read_only_wrapper_raises_on_writes_and_delegates_reads` |
| 5 | `test_fusion_guard_factory.py::test_build_fusion_client_uses_default_pod` |
| 6 | `test_fusion_fake.py::test_fake_satisfies_protocol` (static `FusionClient` assignment checked by pyright + runtime method-set equality with `HttpFusionClient`) |
| 6 | `test_fusion_fake.py::test_apply_updates_balance_and_unapplied` |
| 6 | `test_fusion_fake.py::test_overapply_and_already_applied_faults` |
| 6 | `test_fusion_fake.py::test_unapply_restores_ledger` |
| 6 | `test_fusion_fake.py::test_seeded_from_json_fixture_and_scenario_round_trip` (`scenarios/basic.json`; `FusionScenario.to_json()` → `from_json` equal ledgers) |
| 6 | `test_fusion_fake.py::test_fake_rest_post_surface_for_testdata` (invoice POST, completeTransaction, credit memo, receipt POST create readable rows; unknown path → 404 FusionError) |
| 6 | `test_fusion_fake.py::test_fake_honours_write_guard_and_fail_next` |
| 7 | `api/tests/live/fusion/test_fusion_live.py::test_live_<call>` one per call (`find_transactions`, `find_receipts`, `receipts_created_since`, `get_receipt`, `list_receipt_applications`, `list_transaction_applications`, `get_customer_account`, `customer_relationships`, `run_report`), `@pytest.mark.live`, skipped unless settings load and the pod named by `CASHAPP_FUSION_LIVE_POD` exists with `is_production=False`. Write probes (`apply_receipt`/`unapply_receipt`/comment/attachment) also require `fusion.write_enabled` and `CASHAPP_FUSION_LIVE_WRITES=1` and use s23-tagged data only. Each passing probe calls `record_confirmation(call, fields)`, which appends `CONFIRMED <date> <pod>` to `CONTRACTS.md` when `CASHAPP_FUSION_RECORD_CONTRACTS=1`. |
| 7 | `test_fusion_guard_factory.py::test_contracts_md_lists_every_unverified_marker` (every `# UNVERIFIED:` tag in the package has a `CONTRACTS.md` row; unit, not live) |

## Risks

- **Field and resource names.** Most names beyond reference doc §3 (`EnteredAmount`, `BillToSite`,
  credit memo currency/status, `CreationDate` filter format, receipt/transaction application
  children, customer account resource, `Comments`, attachments, unapply operation, apply response
  `ReceivableApplicationId`, SOAP namespaces/`SOAPAction`) are UNVERIFIED. The coder may confirm REST
  shapes read-only with `aix-greenlight` `fusion_rest_describe`/`fusion_rest_get` (never
  `fusion_rest_write`) and updates `CONTRACTS.md`; nothing else depends on the guess because every
  name lives in `query.py`/`soap.py` constants.
- **No REST application listing.** If neither child resource exists, `list_*_applications` moves to a
  BIP data model; that requires s32 to ship `receipt_applications.sql`. The method signatures do not
  change.
- **Double apply on ambiguous timeouts.** Mitigated by not retrying writes after a possibly-processed
  request (`outcome_unknown=True`) and by s15's idempotency check before every apply.
- **s29 lands in the same wave.** `span`/`get_logger` are imported from `cashapp.observability.tracing`
  and `cashapp.observability.logging` per s29's story AC. If s29 is not merged first, the merger
  rebases; no local stand-in is created (DRY).
- **Credit memo sign.** The plan normalizes to `-abs(...)`. If the live probe shows Fusion ever
  returns a positive balance meaning a debit on a credit memo, revisit.
- **URL length.** 50 quoted numbers per `in (...)` keeps URLs well under common limits; the chunk
  size is an option, not a constant in callers.
- **s39 edits this package** (`get_payment_terms` on the Protocol, client and fake). That is a planned
  later edit; s05 leaves no placeholder for it.

## Assumptions / deviations

- Retry "max 3" is 3 attempts in total. Writes retry only on failures where Fusion certainly did not
  process the request; other transient write failures raise at once with `outcome_unknown=True`
  (stricter than the AC's blanket retry, to prevent double application).
- `FUSION_LOCKED` faults from SOAP come back in `ApplyResult.fault` and are not retried inside the
  client; s18's backoff handler retries them. Only `FUSION_TRANSIENT` is retried in-client.
- Business faults from `apply_receipt`/`unapply_receipt` are returned in the result; transport,
  guard and parse-of-HTTP failures raise `FusionError`. `FusionError.from_fault` lets callers raise
  uniformly.
- `get_customer_account` raises `FusionError(CUSTOMER_NOT_FOUND)` when no row exists.
- Client tuning (timeouts, page size, chunk size, retry counts) lives in `FusionClientOptions`
  defaults, not in s27 settings or s28 runtime config; no settings change is made.
- `FusionClient` gains `pod_name` and `aclose()` beyond the AC list (s30 closes clients on shutdown).
- `read_only()` is provided here because s12 and s32 both need it (one implementation).
- The relationships report parameter and row shape are pinned here; s32 builds the report to match.
- BIP authentication uses HTTP basic with the pod's integration user (UNVERIFIED).
- `CONTRACTS.md` is updated by an opt-in env flag during live runs, not on every live run.
