# s41-ops-reports-daily-summary: plan

Issue #41, wave 5. Owns `web/app/(shell)/reports/**`, `web/components/reports/`, `web/lib/reports/`,
`api/src/cashapp/services/reports/`, `api/src/cashapp/api/routers/reports.py`, and one appended block in
`api/src/cashapp/pollers/intake/hooks.py` (s06's file, append-only, the same pattern as s45).

No scheduler. A report is generated when someone asks for it, or by the intake poller's first cycle after
`reports.daily_summary_cutover` (UTC). That cycle is the only automatic trigger. Statuses, error codes, stages
and money come from s02's registries and are never redeclared.

## Standards followed

- **CLAUDE.md:**
  - Layers: router, then service, then repository.
  - Only `data/repositories/reports.py` builds SQLAlchemy queries.
  - Services take `uow` and `Principal` as plain arguments and never touch `Request`.
  - One error shape (s01 `ApiError`).
  - Money is `Decimal` and always carries its currency (`MoneyStr` in JSON).
  - One status enum (`LineStatus`, `APPLIED_LINE_STATUSES`, `SUCCESS_STATUSES` from s02).
  - No third poller. The hook rides the existing intake loop (non-negotiable 5).
  - Everything is auditable: each `REPORT_RUN` row records who or what generated and emailed it.
- **python-web-app:** routes stay thin, logic lives in services, `Annotated` dependency aliases, and
  every schema change is an Alembic revision.
- **s02 naming:** lowercase ORM names, upper-case physical names, `identity_pk()`, `JsonDoc`,
  `UtcDateTime`, enum columns as `VARCHAR2(40)` with no CHECK, constraint names of 30 characters or fewer.
- **nextjs-fullstack-standards + bmn `nextjs.md`:**
  - Server Components by default; `"use client"` only on leaves (RC-5, RC-6, RC-7).
  - Zod at every boundary: searchParams, action input and route params (TS-17, TS-19, API-8, DF-13).
  - `PageProps<'/reports'>` and `RouteContext` (TS-13, TS-15, TS-16, RC-13).
  - Errors are returned as values, as `Result` (TEST-18, DF-14).
  - Server Actions check auth themselves through s31 `apiAction` and the API (DF-11, DF-12).
  - The download Route Handler sits under `app/api/`, never beside a page (API-1, API-5, API-13).
  - `loading.tsx` and `error.tsx` (RT-8, TEST-19, TEST-20, TEST-21).
  - E2E uses role locators (TEST-12, TEST-14, TEST-17).
  - `server-only` (TS-27).
  - No `any` and no `as` in place of validation (TS-28, TS-32).
  - `readonly` data (TS-31).
  - Discriminated-union UI states (TS-30).
- **design.md §8 and §9:** reuse s19's `kpi-card`, `data-table`, `money`, `empty-state` and `error-alert`.
  Use shadcn `tabs`, `card`, `chart` (recharts), `calendar`, `popover`, `dialog`, `button` and `skeleton`.
  These are already present in `web/components/ui/`, except `dialog` (present), so no CLI add is needed.
  If `popover` is missing at code time, run `npx shadcn@latest add popover`.

## Files to touch

### API (`api/`)

| Path | Purpose |
|---|---|
| `alembic/versions/s41_report_run.py` | The one revision (see Migrations). |
| `src/cashapp/domain/reports.py` | `ReportKind`, `GENERATED_BY_CUTOVER`, `AgingBucket`, `AGING_BUCKETS`, `bucket_for(age)`. Pure. |
| `src/cashapp/data/models/report_run.py` | `ReportRun` ORM model. `load_all_models()` picks it up. |
| `src/cashapp/data/repositories/reports.py` | `ReportRunRepository` and `ReportQueryRepository`: every aggregate query over WORK_ITEM, WORK_ITEM_HISTORY and LINE_RESULT. |
| `src/cashapp/services/reports/__init__.py` | Re-exports the public names. Does **not** register the hook. |
| `src/cashapp/services/reports/models.py` | Frozen dataclasses `DailySummary`, `CurrencyAmount`, `ErrorCodeCount`, `AgingBucketCount`, `PartiallyPaidRow`, `ReportRunInfo`. |
| `src/cashapp/services/reports/daily_summary.py` | `daily_summary(uow, day)`. |
| `src/cashapp/services/reports/partially_paid.py` | `partially_paid(uow, from_, to)`. |
| `src/cashapp/services/reports/export.py` | `to_csv` and `to_xlsx` for both reports, with stable headers (openpyxl is already pinned by s01). |
| `src/cashapp/services/reports/service.py` | `ReportService`: `get_daily`, `generate_daily`, `email_daily`, `run_cutover`. |
| `src/cashapp/services/reports/hook.py` | `DailySummaryCycleHook`. |
| `src/cashapp/api/schemas/reports.py` | Pydantic v2 response and request schemas. |
| `src/cashapp/api/routers/reports.py` | `router`, auto-discovered (`main.py` untouched). |
| `src/cashapp/pollers/intake/hooks.py` | **Append only:** a guarded registration of `DailySummaryCycleHook()`. |
| `tests/unit/reports/…`, `tests/api/test_reports_api.py`, `tests/integration/test_report_run_migration_atp.py`, `tests/support/reports.py` | Written in step 5 only. |

### Web (`web/`)

| Path | Purpose |
|---|---|
| `app/(shell)/reports/page.tsx` | Server Component. Parses `searchParams` (`tab`, `date`, `from`, `to`) with Zod, calls `api()` and renders the tabs. |
| `app/(shell)/reports/loading.tsx` | Skeletons: 4 KPI cards, the chart and the table. |
| `app/(shell)/reports/error.tsx` | `"use client"` boundary. Shows a generic `error-alert` with Retry (`reset()`). |
| `app/(shell)/reports/actions.ts` | `"use server"`: `generateDailySummary`, `emailDailySummary` via s31 `apiAction` plus Zod, then `refresh()`. |
| `app/api/reports/[report]/export/route.ts` | `GET`. Validates `report ∈ {daily-summary, partially-paid}`, `format ∈ {csv, xlsx}` and the dates, then streams the API's file through with `Content-Disposition`. |
| `components/reports/reports-tabs.tsx` | `"use client"`. Tabs bound to `?tab=` via `<Link>`/router (Daily summary · Partially paid invoices). |
| `components/reports/daily-summary-view.tsx` | Server. KPI strip, chart, aging table, the "Last generated …" line and the empty state. |
| `components/reports/failures-by-code-chart.tsx` | `"use client"`. shadcn `ChartContainer` with a recharts `BarChart`, horizontal bars, `--status-error`. |
| `components/reports/aging-table.tsx` | Server. shadcn `table` of the 4 buckets. |
| `components/reports/report-date-picker.tsx` | `"use client"`. `Popover` + `Calendar`; updates `?date=` (single) or `?from=&to=` (range). |
| `components/reports/daily-summary-actions.tsx` | `"use client"`. Generate now, the Email to list… `Dialog` (recipients textarea, optional), and the error alert with Retry for action failures. |
| `components/reports/export-buttons.tsx` | Server. Two `<a download>` buttons pointing at the export route. |
| `components/reports/partially-paid-table.tsx` | `"use client"`. s19 `data-table` with the columns from AC6, and the WI link. |
| `lib/reports/schemas.ts` | Zod: `reportsSearchParams`, `generateInput`, `emailInput` (email list, max 50), `exportParams`. |
| `lib/reports/format.ts` | `formatReportDate("2026-10-22") -> "22 Oct 2026"`, `yesterdayUtc(now)`, `lastGeneratedLabel(info, cutover)`. |
| `lib/api/file.ts` | **New file in s31's folder (additive):** `apiFile(path, query): Promise<Result<Response, ApiError>>`, the raw-body twin of `api()` that reuses s31's base URL, token and request-id code. See Assumptions. |
| `tests/unit/reports/*.test.ts(x)`, `e2e/reports.spec.ts` | Step 5 only. |

`web/lib/api/openapi.json` and `schema.ts` are regenerated with `npm run api:sync`. They're generated files, so on a merge conflict the merger regenerates them and never hand-merges.

## Design

### Domain (`domain/reports.py`)

```python
class ReportKind(StrEnum): DAILY_SUMMARY = "DAILY_SUMMARY"
GENERATED_BY_CUTOVER: Final = "first-event-after-cutover"
GENERATED_BY_USER_PREFIX: Final = "user:"            # GENERATED_BY = "user:<principal.subject>"
@dataclass(frozen=True, slots=True)
class AgingBucket: key: str; label: str; min_days: int; max_days: int | None
AGING_BUCKETS: Final[tuple[AgingBucket, ...]] = (
    AgingBucket("0-2d", "0–2 days", 0, 2), AgingBucket("3-7d", "3–7 days", 3, 7),
    AgingBucket("8-30d", "8–30 days", 8, 30), AgingBucket("gt30d", "Over 30 days", 31, None))
def bucket_for(age_days: int) -> AgingBucket
```

These buckets are the ones design §4 uses on the Awaiting-receipt tile. The flow monitor (s19) should import them too. The rule is one definition.

### Metric definitions (AC2). A day is `[day 00:00Z, day+1 00:00Z)`.

| Field | Definition |
|---|---|
| `items_in` | WORK_ITEM rows with `created_at` in the day, excluding envelope parents (rows that have children: `NOT EXISTS child.parent_id = id`). |
| `completed` | Distinct items with a history row `to_state = DONE` in the day. |
| `auto_applied` | Of `completed`: `payment_status ∈ SUCCESS_STATUSES` and no `HUMAN_ACTION` history row ever. |
| `auto_applied_pct` | `auto_applied / completed × 100`, `Decimal` at 1 dp `ROUND_HALF_UP`. `None` when `completed == 0`. |
| `applied_by_currency` | Sum of `LINE_RESULT.applied_amount` where `line_status ∈ APPLIED_LINE_STATUSES` and `updated_at` is in the day, grouped by the item's `currency`. Sorted by currency. `ALLOCATION_DRY_RUN` is excluded because it isn't in the applied set. |
| `failures_by_error_code` | Distinct `(work_item_id, error_code)` pairs from history rows in the day where `error_code IS NOT NULL`, counted per code, sorted by count descending, then code. |
| `escalations` | Distinct items with a history row `to_state = ESCALATED` in the day. |
| `aging_buckets` | Items whose state is not in `TERMINAL_STATES` and whose `created_at` is before the end of the day. Age = `floor((end_of_day − coalesce(awaiting_since, created_at)) / 1 day)`, put into `AGING_BUCKETS`. Every bucket is returned, including zeros. |
| `has_activity` | `items_in + completed + escalations + Σfailures > 0`. The UI uses it for the empty state. |

Aging uses current state, so a past day computed live is approximate. The stored `REPORT_RUN.PAYLOAD` freezes the figures at generation time, and GET serves the stored payload (see Assumptions).

### Partially paid (AC2)

`LINE_RESULT ⋈ WORK_ITEM` where `line_status IN (ALLOCATION_APPLIED_SHORT_PAY, ALLOCATION_APPLIED_LESS_THAN_INSTRUCTION)` and `updated_at` falls within `[from 00:00Z, to+1 00:00Z)`. Results are ordered by `updated_at DESC, id DESC`, capped at 5,000 rows. Exceeding the cap sets `truncated=True`.

Each row maps as follows:
- `invoice_number` = `transaction_number`
- `customer` = `customer_account_number` and `payer_name`
- `original` = `balance_before`
- `paid` = `applied_amount`
- `remaining` = `balance_before − applied_amount − coalesce(discount_amount, 0)`, using `to_money`
- `currency` = the item's currency
- `short_pay_reason` = `reason`, or the status label when `reason` is null
- `item_id`

### Service (`services/reports/service.py`)

```python
class ReportService:
    def __init__(self, *, clock: Clock | None = None, sender: ReportSender = send_report_email) -> None
    async def get_daily(self, uow, day: date) -> tuple[DailySummary, ReportRunInfo | None]
        # stored REPORT_RUN payload if a row exists, else live daily_summary (not stored)
    async def generate_daily(self, uow, day: date, principal: Principal) -> tuple[DailySummary, ReportRunInfo]
        # compute; upsert REPORT_RUN (insert, or update PAYLOAD/GENERATED_AT/GENERATED_BY on existing); flush only
    async def email_daily(self, uow, day: date, recipients: Sequence[str] | None, principal: Principal,
                          config: ConfigSnapshot) -> ReportRunInfo
        # recipients None -> config.notifications().recipients.get("daily_summary", {}).get("email", ())
        # empty -> ApiError-mapped NoRecipients; no stored row -> generate first (by principal)
        # send_report_email(recipients, subject, body, [(xlsx), (csv)], uow=uow, kind="daily_summary")
        # then EMAILED_TO/EMAILED_AT; ChannelSendError -> ReportEmailFailed (row keeps the old EMAILED_* values)
    async def run_cutover(self, uow_factory: UowFactory, now: datetime, config: ConfigSnapshot) -> bool
        # see hook; returns True when this process generated (and attempted the email)
```

- **Subject:** `[CashApp {ENV}] Daily summary {22 Oct 2026}`.
- **Body:** counts and per-currency totals only. No payer names, which keeps PII out of mail (CLAUDE.md).
- **Attachments:** `daily-summary-2026-10-22.xlsx` and `daily-summary-2026-10-22.csv`.

### Hook (AC4)

```python
class DailySummaryCycleHook:          # satisfies s06 CycleHook structurally; doesn't import hooks.py
    def __init__(self, service: ReportService | None = None) -> None
    _done_for: date | None            # in-process gate, so the DB isn't hit on every cycle once handled
    async def on_cycle(self, container: Container, now: datetime) -> None
```

On each cycle:

1. Take one config snapshot. Read `cutover = cfg.reports().daily_summary_cutover`.
2. If `now.time() < cutover`, or `_done_for == now.date()`, return.
3. Set `report_date = now.date() - 1 day`. If a `REPORT_RUN` row already exists for `(DAILY_SUMMARY, report_date)`, set `_done_for` and return.
4. Otherwise compute and insert with `GENERATED_BY = GENERATED_BY_CUTOVER`, then commit.
   - A unique violation (`is_unique_violation` from s06) means another process won the race. Set `_done_for` and return without emailing.
5. Only the process that inserted the row sends the email, in a second UoW: `send_report_email(... uow=uow, kind="daily_summary")`. It sets `EMAILED_TO` and `EMAILED_AT`, then commits.
   - If the send fails, it logs the class name only and leaves `EMAILED_AT` null. s42 already wrote the failed `NOTIFICATION_LOG` row. There's no automatic resend, so a person can use Email to list…
6. Set `_done_for = now.date()`.

Any exception other than a unique violation propagates to `run_cycle_hooks`, which logs it and swallows it. In that case `_done_for` stays unset, so the next cycle retries the generation.

Registration is appended at the bottom of `hooks.py`:

```python
from cashapp.services.reports.hook import DailySummaryCycleHook  # noqa: E402
if not any(isinstance(h, DailySummaryCycleHook) for h in CYCLE_HOOKS):
    CYCLE_HOOKS.append(DailySummaryCycleHook())
```

### HTTP contract (AC3). Every route requires `reports:read` and uses s01's single error shape.

| Method and path | Request | 200 response |
|---|---|---|
| `GET /reports/daily-summary?date=YYYY-MM-DD&format=json\|csv\|xlsx` | `date` defaults to yesterday (UTC) | json: `DailySummaryResponse`; csv/xlsx: the file |
| `POST /reports/daily-summary/generate` | `{date}` | `DailySummaryResponse` (with `last_generated` set) |
| `POST /reports/daily-summary/email` | `{date, recipients?: list[EmailStr] (1..50)}` | `{date, emailed_to: list[str], emailed_at}` |
| `GET /reports/partially-paid?from=&to=&format=json\|csv\|xlsx` | `from` and `to` default to yesterday; span ≤ 366 days | json: `PartiallyPaidResponse`; csv/xlsx: the file |

```python
class CurrencyAmountOut(BaseModel): currency: CurrencyCode; amount: MoneyStr
class ErrorCodeCountOut(BaseModel): error_code: ErrorCode; count: int
class AgingBucketOut(BaseModel): key: str; label: str; count: int
class LastGeneratedOut(BaseModel): at: datetime; by: str; by_kind: Literal["user", "cutover"]
class DailySummaryOut(BaseModel):
    date: date; items_in: int; completed: int; auto_applied: int
    auto_applied_pct: Decimal | None   # serialized as string "78.4", null when no completions
    applied_by_currency: list[CurrencyAmountOut]; failures_by_error_code: list[ErrorCodeCountOut]
    aging_buckets: list[AgingBucketOut]; escalations: int; has_activity: bool
class DailySummaryResponse(BaseModel):
    summary: DailySummaryOut; last_generated: LastGeneratedOut | None
    emailed_to: list[str]; emailed_at: datetime | None; cutover: str   # "07:00"
class PartiallyPaidRowOut(BaseModel):
    invoice_number: str; customer_account_number: str | None; customer_name: str | None
    currency: CurrencyCode; original: MoneyStr; paid: MoneyStr; remaining: MoneyStr
    short_pay_reason: str; line_status: LineStatus; item_id: int
class PartiallyPaidResponse(BaseModel): from_: date (alias "from"); to: date; rows: list[PartiallyPaidRowOut]; truncated: bool
class GenerateRequest(BaseModel): date: date
class EmailRequest(BaseModel): date: date; recipients: list[EmailStr] | None = None
class EmailResponse(BaseModel): date: date; emailed_to: list[str]; emailed_at: datetime
```

`last_generated.by` is `"first event after <cutover> cutover"` for a cutover run, or the user's display name (`GENERATED_BY_NAME`).

Errors:

| Status | Code | When |
|---|---|---|
| 422 | `invalid_range` | `from > to`, or the span is longer than 366 days |
| 422 | `invalid_date` | the date is in the future |
| 422 | `no_recipients` | no list was passed and nothing is configured |
| 502 | `report_email_failed` | the channel raised `ChannelSendError`. Details carry the reason class only. |
| 403 | | from s04 |
| 422 | | the framework's own validation error for a bad `format` |

Files (csv and xlsx):

- **Content types:** `text/csv; charset=utf-8` or `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- **Download name:** `Content-Disposition: attachment; filename="daily-summary-2026-10-22.csv"` (and the matching xlsx name).
- **Encoding:** the CSV is UTF-8 with no BOM and `\r\n` line ends, from the `csv` module. Money is written as a 2 dp string.

Stable headers, pinned as module constants in `export.py`:

- `DAILY_SUMMARY_COLUMNS = ("section", "key", "currency", "value")`. Rows come in this order:
  1. `kpi` rows: `items_in`, `completed`, `auto_applied`, `auto_applied_pct`, `escalations`
  2. `applied_by_currency` rows, with the currency set
  3. `failures_by_error_code` rows
  4. `aging` rows
- `PARTIALLY_PAID_COLUMNS = ("invoice_number", "customer_account_number", "customer_name", "currency", "original", "paid", "remaining", "short_pay_reason", "item_id")`.
- The XLSX has one sheet with the same header row. Money cells are numeric with the format `#,##0.00`, and a frozen header row.
- Cell values are written as values, never formulas. Any string starting with `= + - @` is prefixed with `'`, to block CSV and XLSX formula injection, because payer names are untrusted.

### Web

- **`page.tsx`:**
  - Runs `requireSession()`.
  - Parses with `reportsSearchParams`. A bad value falls back to the default; it never throws.
  - For `tab=daily` it calls `api("get", "/reports/daily-summary", {query:{date}})`. For `tab=partial` it calls `api("get", "/reports/partially-paid", {query:{from,to}})`. Only the active tab is fetched.
  - A failure renders s19's `error-alert` with the request id and a Retry link to the same URL.
  - A 403 shows design §3's unauthorized empty state.
- **Daily tab:**
  - KPI cards: Items in; Auto-applied % (`—` when null); Amount applied by currency, one `money` line per currency; Escalations.
  - Chart: "Failures by error code".
  - Table: "Aging items".
  - Buttons: Generate now, Email to list…, Export CSV, Export XLSX.
  - When `has_activity` is false, the empty state reads "No activity on 22 Oct 2026." and the buttons stay usable.
  - The "Last generated" line comes from `lastGeneratedLabel`:
    - `"Last generated 07:02 by first event after 07:00 cutover."` for a cutover run
    - `"Last generated 09:14 by J. Stevenson."` for a user run
    - `"Not generated yet."` when there's no run
    - Times are shown in UTC HH:mm.
- **Actions:** `generateDailySummary({date})` and `emailDailySummary({date, recipients?})` are built with `apiAction(schema, fn)`.
  - They return `Result`. On ok they call `refresh()`.
  - The client shows a `sonner` toast on success: "Daily summary generated" or "Emailed to 3 recipients".
  - On error it shows the inline destructive `Alert` "Couldn't generate the report. … (request id …)" with **Retry**, which re-invokes the same action.
- **Export route:**
  - `GET /api/reports/[report]/export?format=&date=|from=&to=` runs `getSession()` and answers 401 with the envelope if there's no session.
  - It Zod-validates, then calls `apiFile` and passes through `body`, `Content-Type` and `Content-Disposition`, and nothing else (API-29).
  - API errors are mapped to the JSON envelope with the same status.
- **Partially paid tab:**
  - A range picker and the `data-table` with these columns:
    - Invoice # (mono)
    - Customer (account number · name)
    - Original, Paid and Remaining (`money`, right-aligned)
    - Short-pay reason
    - WI: `<Link href="/items/{id}">WI-{id}</Link>`. The workbench deep link `/exceptions?item=` is used only when the item is not DONE; partially-paid items are DONE, so `/items/[id]` applies.
  - Export CSV and XLSX buttons.
  - The empty state reads "No partially paid invoices between 1 Oct 2026 and 22 Oct 2026."
  - When `truncated` is true, a muted note reads "Showing the latest 5,000 rows; export for all."
- **Nav:** s19's sidebar owns the Reports item, filtered by `reports:read` from `/me` (design §3). s41 adds no nav code; AC7's browser test asserts the item is there.

## Interfaces provided (pinned)

```python
# cashapp/domain/reports.py
class ReportKind(StrEnum): DAILY_SUMMARY = "DAILY_SUMMARY"
GENERATED_BY_CUTOVER: Final[str]  # "first-event-after-cutover"
GENERATED_BY_USER_PREFIX: Final[str]  # "user:"
AgingBucket; AGING_BUCKETS: tuple[AgingBucket, ...]; def bucket_for(age_days: int) -> AgingBucket   # s19 reuses

# cashapp/services/reports/models.py  (frozen, slots)
CurrencyAmount(currency: str, amount: Decimal); ErrorCodeCount(error_code: ErrorCode, count: int)
AgingBucketCount(key: str, label: str, count: int)
DailySummary(day: date, items_in: int, completed: int, auto_applied: int, auto_applied_pct: Decimal | None,
             applied_by_currency: tuple[CurrencyAmount, ...], failures_by_error_code: tuple[ErrorCodeCount, ...],
             aging_buckets: tuple[AgingBucketCount, ...], escalations: int, has_activity: bool)
    def to_payload(self) -> dict[str, Any]; @classmethod def from_payload(cls, p: Mapping[str, Any]) -> "DailySummary"
PartiallyPaidRow(invoice_number, customer_account_number, customer_name, currency, original, paid, remaining,
                 short_pay_reason, line_status: LineStatus, item_id: int)
ReportRunInfo(id: int, kind: ReportKind, report_date: date, generated_at: datetime, generated_by: str,
              generated_by_name: str, emailed_to: tuple[str, ...], emailed_at: datetime | None)

# cashapp/services/reports/daily_summary.py / partially_paid.py
async def daily_summary(uow: UnitOfWork, day: date) -> DailySummary
PARTIALLY_PAID_STATUSES: Final[frozenset[LineStatus]]   # SHORT_PAY, LESS_THAN_INSTRUCTION
PARTIALLY_PAID_MAX_ROWS: Final = 5000
async def partially_paid(uow: UnitOfWork, from_: date, to: date) -> tuple[list[PartiallyPaidRow], bool]  # (rows, truncated)

# cashapp/services/reports/export.py
ExportFormat = Literal["csv", "xlsx"]
DAILY_SUMMARY_COLUMNS: Final[tuple[str, ...]]; PARTIALLY_PAID_COLUMNS: Final[tuple[str, ...]]
def daily_summary_file(s: DailySummary, fmt: ExportFormat) -> tuple[str, bytes, str]   # (filename, content, content_type) == s42 Attachment
def partially_paid_file(rows: Sequence[PartiallyPaidRow], from_: date, to: date, fmt: ExportFormat) -> tuple[str, bytes, str]

# cashapp/services/reports/service.py
class NoRecipients(Exception); class ReportEmailFailed(Exception): reason: str; class FutureReportDate(ValueError)
ReportSender = Callable[..., Awaitable[None]]   # send_report_email's signature
class ReportService: (signatures above)

# cashapp/services/reports/hook.py
class DailySummaryCycleHook: async def on_cycle(self, container: Container, now: datetime) -> None

# cashapp/data/repositories/reports.py
class ReportRunRepository(BaseRepository[ReportRun]):
    async def find(self, kind: ReportKind, report_date: date) -> ReportRun | None
class ReportQueryRepository:      # read-only aggregates; takes the UoW session
    def __init__(self, session: AsyncSession) -> None
    async def items_in(self, start: datetime, end: datetime) -> int
    async def completions(self, start, end) -> tuple[int, int]               # (completed, auto_applied)
    async def applied_by_currency(self, start, end) -> list[tuple[str, Decimal]]
    async def failures_by_code(self, start, end) -> list[tuple[ErrorCode, int]]
    async def escalations(self, start, end) -> int
    async def open_item_ages(self, end: datetime) -> list[datetime]           # coalesce(awaiting_since, created_at)
    async def partially_paid(self, start, end, statuses, limit: int) -> list[Row]
```

HTTP: the routes and schemas above, under OpenAPI tag `reports`. Web: `web/lib/api/file.ts` `apiFile(path: ApiPath, query?: Record<string,string>, init?: {signal?: AbortSignal; requestId?: string}): Promise<Result<Response, ApiError>>`, which is server-only.

## Migrations

One hand-written revision, `api/alembic/versions/s41_report_run.py`, with `revision = "s41_report_run"`.

- **Expected parent:** the Alembic head when this story merges. In wave 5 that is s15's `LINE_RESULT`/`APPLICATION_LEDGER` revision, or whichever wave-5 revision merges last before this one; the coder writes it against the current head. The merger re-points `down_revision` and checks that `alembic heads` returns exactly one head. The revision has no FK to other tables, so its order doesn't matter. Apply it to DEV ATP only.

Table `report_run` (physical `REPORT_RUN`):

| Column | Type |
|---|---|
| `ID` | identity PK (`PK_REPORT_RUN`) |
| `KIND` | `VARCHAR2(40) NOT NULL` (`ReportKind`, no CHECK) |
| `REPORT_DATE` | `DATE NOT NULL` |
| `GENERATED_AT` | `TIMESTAMP WITH TIME ZONE NOT NULL` |
| `GENERATED_BY` | `VARCHAR2(255) NOT NULL`: `first-event-after-cutover` or `user:<subject>` |
| `GENERATED_BY_NAME` | `VARCHAR2(255) NOT NULL`: the display name, or `CashApp automation` (additive, see Assumptions) |
| `PAYLOAD` | `JSON NOT NULL` (`DailySummary.to_payload()`, Decimal as string) |
| `EMAILED_TO` | `JSON NULL` (list of str) |
| `EMAILED_AT` | `TIMESTAMP WITH TIME ZONE NULL` |

- Unique constraint `UQ_REPORT_RUN_KIND_DATE (KIND, REPORT_DATE)`. Its index also serves lookups.
- Downgrade drops the table.

No other DDL. The queries use existing indexes:
- `IX_WORK_ITEM_STAGE_STATE`
- `IX_WIH_ITEM_AT`, plus a full scan of the day's history, which is fine at expected volumes. See Risks.
- s15's `LINE_RESULT` unique `(WORK_ITEM_ID, LINE_NO)`

## TEST PLAN (written and run in step 5 only)

Helpers: s02 `uow` and `FrozenClock`, s04 `make_principal`/`override_principal`, s28 `make_config_snapshot`, s42 `FakeChannel`. New `tests/support/reports.py` adds `seed_report_day(uow, day)`. It builds WORK_ITEM, history and LINE_RESULT rows for a known mix: 2 currencies, 3 error codes, 1 escalation, 1 human-touched success, open items in each aging bucket, and 1 envelope parent.

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `tests/integration/test_report_run_migration_atp.py::test_report_run_upgrade_downgrade_atp` (`-m atp`) | The table has the exact columns and types, native `JSON`, identity PK and `UQ_REPORT_RUN_KIND_DATE`. Downgrade drops it. `alembic heads` returns one head. |
| 1 | `tests/unit/reports/test_report_run_model.py::test_unique_kind_date_and_payload_roundtrip` | sqlite: the payload round-trips with Decimal as a string; a second `(KIND, REPORT_DATE)` insert raises a unique violation (`is_unique_violation` is True). |
| 2 | `tests/unit/reports/test_daily_summary.py::test_counts_for_seeded_day` | The exact `items_in` (envelope excluded), `completed`, `auto_applied`, `auto_applied_pct` (`Decimal("66.7")`, half-up) and `escalations`. |
| 2 | `…::test_applied_by_currency_uses_applied_statuses_only` | `USD` and `INR` sums are exact Decimals. Dry-run and failed lines are excluded. Rows outside the day are excluded. |
| 2 | `…::test_failures_by_error_code_distinct_per_item` | The same item and code twice in a day counts once. Sorted by count descending, then code. |
| 2 | `…::test_aging_buckets_all_present_and_boundaries` | Ages 2, 3, 7, 8, 30 and 31 land in the right buckets. Zero buckets are still returned. `awaiting_since` beats `created_at`. |
| 2 | `…::test_empty_day_has_no_activity_and_null_pct` | `has_activity` is False and `auto_applied_pct` is None. |
| 2 | `…::test_payload_roundtrip` | `from_payload(to_payload(s)) == s`. |
| 2 | `tests/unit/reports/test_partially_paid.py::test_rows_from_short_pay_statuses_only` | Only the two statuses. The original, paid and remaining arithmetic includes the discount. The reason falls back to the status label. The range is inclusive of `to`. |
| 2 | `…::test_truncates_at_max_rows` | With the cap monkeypatched to 3: 3 rows and `truncated` is True. |
| 2 | `tests/unit/reports/test_aging_bucket.py::test_bucket_for_edges` | 0, 2, 3, 7, 8, 30, 31, 400. A negative value raises `ValueError`. |
| 3 | `tests/api/test_reports_api.py::test_get_daily_summary_live_then_stored` | Without a run: 200, `last_generated` null and the shape matches. After generate: the stored payload is served and `last_generated.by_kind == "user"`. |
| 3 | `…::test_get_daily_summary_defaults_to_yesterday` | Uses a FrozenClock override. |
| 3 | `…::test_generate_upserts_single_row` | Two generates leave one REPORT_RUN row; `GENERATED_AT` and the name are updated. |
| 3 | `…::test_email_defaults_to_configured_recipients` | Config `notifications.recipients.daily_summary.email` is used. FakeChannel got the subject, an xlsx and a csv attachment, and the body has no payer names. `EMAILED_TO`/`EMAILED_AT` are set. |
| 3 | `…::test_email_explicit_recipients_and_no_recipients_422` | Explicit list is used; neither present → 422 `no_recipients`. |
| 3 | `…::test_email_channel_failure_502` | 502 `report_email_failed`, single error shape; `EMAILED_AT` unchanged. |
| 3 | `…::test_partially_paid_json_and_invalid_range` | 200 rows; `from > to` → 422 `invalid_range`; future date → 422 `invalid_date`. |
| 3 | `…::test_csv_export_stable_headers` (parametrized over both reports) | The `Content-Type` and `Content-Disposition` filename are right, and the first CSV line equals `",".join(COLUMNS)`. |
| 3 | `…::test_xlsx_export_opens_with_openpyxl` | Header row equals COLUMNS; money cells are numeric with format `#,##0.00`; a `=cmd` payer name is stored as text with a `'` prefix. |
| 3 | `…::test_all_report_routes_require_reports_read` | A principal without `reports:read` gets 403 with the error shape on all 4 routes. |
| 4 | `tests/unit/reports/test_cycle_hook.py::test_before_cutover_does_nothing` | 06:59 UTC: no row and no email. |
| 4 | `…::test_first_cycle_after_cutover_generates_and_emails_yesterday_once` | 07:00:05: one row for yesterday with `GENERATED_BY = first-event-after-cutover` and exactly one FakeChannel message. A second cycle at 07:05 sends nothing more and makes no extra query (in-process gate). |
| 4 | `…::test_existing_row_skips` | A row created by a user earlier: the hook doesn't regenerate or email. |
| 4 | `…::test_two_processes_race_emails_once` | Two hook instances on a shared sqlite engine run concurrently (`asyncio.gather`). There's one row and one email; the loser hits the unique violation and stays silent. |
| 4 | `…::test_generation_error_retries_next_cycle` | The first cycle raises (propagated). The next cycle generates. |
| 4 | `…::test_email_failure_leaves_emailed_at_null_and_no_resend` | FakeChannel fails, so `EMAILED_AT` is None and the next cycle doesn't resend. |
| 4 | `…::test_hook_registered_once_in_cycle_hooks` | Importing and reloading `cashapp.pollers.intake.hooks` leaves exactly one `DailySummaryCycleHook`. |
| 4 | `…::test_cutover_read_from_config` | With cutover `"09:30"`, 09:00 does nothing and 09:31 generates. |
| 5 | `web/e2e/reports.spec.ts › daily summary tab renders KPIs, chart, aging and actions` | The date picker shows yesterday. There are 4 KPI cards by name. The "Failures by error code" chart and "Aging items" table are present. Buttons Generate now, Email to list…, Export CSV and Export XLSX are present. The line reads "Last generated 07:02 by first event after 07:00 cutover." |
| 5 | `› generate now and email to list call the API and confirm` | A success toast appears. The email dialog accepts recipients. |
| 5 | `› export buttons download files with stable names` | `page.waitForEvent("download")`, with the `suggestedFilename` checked. |
| 5 | `web/tests/unit/reports/format.test.ts › formatReportDate, yesterdayUtc and lastGeneratedLabel` | Labels for both the user and cutover kinds, plus the null case. |
| 5 | `web/tests/unit/reports/export-route.test.ts › validates params, proxies file headers only, 401 without session` | Uses the s31 msw `mockApi`. |
| 6 | `web/e2e/reports.spec.ts › partially paid tab shows data-table with WI links and export` | The columns, `money` formatting with the currency, a WI link to `/items/<id>`, and the export buttons. |
| 7 | `› loading skeletons render` | Skeletons appear while the stub API delays the response. |
| 7 | `› empty day shows "No activity on 22 Oct 2026."` | |
| 7 | `› generation error shows alert with Retry and retry succeeds` | The stub API fails once, then succeeds. |
| 7 | `› Reports nav visible with reports:read, hidden without` | `withSession` with the VIEWER role (has `reports:read`) versus a role set without it. A direct visit by a user without it shows the unauthorized state. |
| 7 | `web/tests/unit/reports/schemas.test.ts › bad searchParams fall back to defaults; email list validated` | |

E2E runs against a production build (TEST-12) with `API_BASE_URL` pointing at the e2e API stub that s19 provides for its own browser tests. s41 adds the `/reports/*` fixtures to that stub. See Risks.

## Assumptions / deviations

- **`LINE_RESULT` column names:** taken from s15's story AC2 (`transaction_number`, `balance_before`, `applied_amount`, `discount_amount`, `line_status`, `reason`, `updated_at`), because s15's plan isn't written yet. Model import: `cashapp.data.models.line_result.LineResult`. The merger fixes the path if s15 names it differently.
- **"Original" amount:** this is `BALANCE_BEFORE`, the invoice balance when the line was applied. `LINE_RESULT` doesn't store the Fusion original invoice amount. Fetching it live from Fusion for a report would add Fusion load, so it's out of scope.
- **Customer:** the item's `customer_account_number` and `payer_name`, because `LINE_RESULT` has no customer column.
- **GET serves stored data:** `GET /reports/daily-summary` serves the stored `REPORT_RUN` payload when one exists, so a report already emailed doesn't drift. Otherwise it computes live and doesn't persist. **Generate now** recomputes and overwrites. Only the daily summary is persisted; partially paid is always computed on demand.
- **`GENERATED_BY_NAME`:** an additive column beyond AC1's list, so the UI can show "by J. Stevenson" without a user table.
- **Permission:** all four routes, including generate and email, require `reports:read`, because s04 defines no `reports:write`. Generation is idempotent, and email only goes to configured or explicitly entered recipients.
- **Report days and the cutover are UTC** (story assumption). The hook compares `now.time()` (UTC) with the cutover.
- **Recipients:** `notifications.recipients` is `kind -> channel -> list` (s28's shape), so the default is `recipients["daily_summary"]["email"]`. The story's `notifications.recipients.daily_summary` is read the same way.
- **Hook registration:** the hook is appended in `hooks.py`, as s45 does, rather than in the services package `__init__`. A services module isn't a role package, so s30's discovery wouldn't import it. The `isinstance` guard prevents a double append.
- **`web/lib/api/file.ts`:** a new additive file in s31's folder. `api()` parses JSON, and `apiStream` accepts only stream paths. If s31 already exports a raw-response helper, use it and drop this file (non-negotiable 7).
- **Reports nav:** the nav item belongs to s19's shell; s41 only verifies it.
- **Aging buckets:** design §4's buckets (0–2d, 3–7d, 8–30d, over 30d), pinned once in `domain/reports.py`.

## Risks

- **Moving targets:** s15 and s19 aren't planned yet, so column, model and component names may shift. The merger reconciles imports. s19's `data-table` and `kpi-card` props are coded against design §9's names.
- **E2E stub:** if s19 ships no e2e API stub, s41's browser tests need one. In that case add `web/e2e/support/api-stub.ts`, a node `http` server started in Playwright `globalSetup`, with `API_BASE_URL` set in the `webServer` env. Flag this to the merger as shared infrastructure.
- **Historical aging:** a past day computed live shows current aging, not aging as of that day. The stored payload limits the impact.
- **History scan:** counting a day's history scans by `at` with no index on `AT` alone. That's acceptable at the expected volume (thousands per day). If it gets slow, add `IX_WIH_AT` in a later revision.
- **Concurrent hooks:** two processes rely on the unique constraint. A crash after insert but before the email leaves the row un-emailed, with no automatic resend. That's deliberate: never double-send. A person uses **Email to list…**.
- **Regenerated contract:** OpenAPI and `schema.ts` are regenerated files that conflict across wave-5 stories. The merger regenerates them with `npm run api:sync`.
- **Formula injection:** CSV and XLSX would carry untrusted payer and reason text. Mitigated by the `'` prefix and by writing values only, never formulas.
