# s42-notifications plan

Issue #42. Wave 4. breaking: false. No UI: the configuration screen (s21) edits `notifications.*` keys generically.

## Standards followed

- **CLAUDE.md**
  - Layered architecture. The router calls a service, the service calls repositories, and only `cashapp/data/` touches SQLAlchemy.
  - Integrations sit behind a Protocol (`NotificationChannel`), with exactly two implementations per external system, the real one and a fake (research.md).
  - No scheduler and no third poller. The consumer reacts to bus events. Its flush timer only drains events it has already buffered and never polls anything external. The sources run inside s30's existing health tick and are not a new loop.
  - PII stays inside OCI and out of messages. Bodies carry item ids, error codes, counts and links only.
  - Every limit is configuration.
- **python-web-app:building-python-web-apps.** External SDK calls are isolated in service and integration modules. Routes only parse and validate. One error shape (s01 `ApiError`).
- **s02 rules**
  - Lowercase SQLAlchemy names of at most 30 characters.
  - Enum-valued columns are `VARCHAR2(40)`-class with no CHECK constraint.
  - JSON goes in `JsonDoc`.
  - Repositories never commit.
  - Exactly one Alembic revision on the current head.
- **s03 rules.** Notify events go only through the outbox (`enqueue`). Offsets are committed only after the log rows are committed.
- **s29.** Logs carry kind, counts and event ids, never bodies, summaries, addresses or webhook URLs.
- **Lockfiles are not edited.** SMTP uses stdlib `smtplib` + `email.message` inside `asyncio.to_thread`. Teams uses `httpx`, which s01 already pins.

## Files

New (all under `api/`):

| Path | Contents |
|---|---|
| `src/cashapp/data/models/notification_log.py` | `NotificationLog` ORM model (picked up by s02 `load_all_models()`) |
| `src/cashapp/data/repositories/notifications.py` | `NotificationLogRepository`, `TransientErrorRepository` |
| `alembic/versions/s42_notification_log.py` | the one revision |
| `src/cashapp/services/notifications/__init__.py` | re-exports the public names below |
| `src/cashapp/services/notifications/channel.py` | `NotificationChannel` Protocol, `ChannelName`, `ChannelSendError`, `Channels`, `build_channels` |
| `src/cashapp/services/notifications/render.py` | `RenderedMessage`, `render_batch` (PII-free body builder) |
| `src/cashapp/services/notifications/batcher.py` | `NotificationBatcher` (pure window logic, no I/O) |
| `src/cashapp/services/notifications/dispatcher.py` | `NotificationDispatcher` (route to channels, send, write log rows) |
| `src/cashapp/services/notifications/emit.py` | `NOTIFY_TOPIC_NAME`, `notify_topic()`, `emit_notification` (only if s18 does not already export an equivalent; see Assumptions) |
| `src/cashapp/services/notifications/sources.py` | `DlqGrowthSource`, `OutageSource`, `NotificationSourcesHook` |
| `src/cashapp/services/notifications/reports.py` | `send_report_email` (public, for s41) |
| `src/cashapp/services/notifications/log_query.py` | `NotificationLogService.list_log` (API read) |
| `src/cashapp/integrations/email/__init__.py` | empty |
| `src/cashapp/integrations/email/smtp.py` | `SmtpEmailChannel` (OCI Email Delivery SMTP) |
| `src/cashapp/integrations/email/teams_webhook.py` | `TeamsWebhookChannel` (incoming webhook via httpx) |
| `src/cashapp/integrations/email/fake.py` | `FakeChannel`, `SentMessage` (tests and `env=local`) |
| `src/cashapp/stations/notify/__init__.py` | `ROLE = RoleSpec("notify", "consumer", NotifyConsumer.build)` |
| `src/cashapp/stations/notify/consumer.py` | `NotifyConsumer` (Runnable) |
| `src/cashapp/api/schemas/notifications.py` | `NotificationLogOut`, `NotificationLogPage` |
| `src/cashapp/api/routers/notifications.py` | `router`: `GET /notifications/log` (auto-discovered, so `main.py` is not edited) |
| tests in the TEST PLAN | written and run in step 5 only |

Edited (append-only, small):

- `src/cashapp/workers/hooks.py` (s30): append `NotificationSourcesHook()` to the `HEALTH_TICK_HOOKS` list literal. s30's plan reserves this one-line edit for s42. The hook module imports only `cashapp.pipeline` / `services` / `data`, never `cashapp.workers.host`.
- `src/cashapp/domain/config_keys.py` (s02 registry; append only):
  - Fix the type of `NOTIFICATIONS_RECIPIENTS` to `dict[str, dict[str, list[str]]]` (kind → channel → addresses/webhooks). s02 pinned it as `dict[str, list[str]]`, but s28's `NotificationsConfig.recipients` and this story's AC2 are nested, so they disagree. Default `{}`. Skip the change if the s28 coder already made it.
  - Append:

    | Key | Type | Default |
    |---|---|---|
    | `notifications.outage_threshold` | `int` (≥ 1) | `10` |
    | `notifications.outage_window_seconds` | `int` (≥ 60) | `300` |
    | `notifications.app_base_url` | `str \| None` | `None` |

  The new keys are read with `snapshot.get(KEY)`. s28's `NotificationsConfig` group class is not edited, which keeps this story file-disjoint from s28.
- `tests/conftest.py`: append `"tests.support.notifications"` to `pytest_plugins` (append only).

Not touched: `settings.py` (s27 already pins `SmtpSettings{host, port=587, username, password: SecretStr, from_address}` and `Settings.smtp: SmtpSettings | None`), `main.py`, lockfiles, s03 relay, s18 escalation.

## Interfaces consumed (coded against the Deps)

- **s18** `cashapp/domain/notifications.py`:
  - `NotifyEvent` (frozen Pydantic): `event_id: UUID`, `kind: Literal["item_escalated","dlq_growth","outage","budget_exceeded"]` (or `str`), `severity: Literal["info","warning","critical"]`, `work_item_id: int | None`, `error_code: ErrorCode | None`, `summary: str`, `occurred_at: datetime`.
  - Topic `default_namer().named("notify")`.
- **s03**: `enqueue`, `default_namer`, `EventBus.subscribe`, `Delivery.commit`, `BusHealth.snapshot()` (`dlq_depth`, -1 = unknown), `RoleSpec`, `Runnable`, `RoleState`, `Container`.
- **s30**: `HealthTickHook.on_tick(container, now)`, `container.resolve(BusHealth)`.
- **s28**: `RuntimeConfig.snapshot()`, `ConfigSnapshot.notifications()` (`recipients`, `batch_window_seconds`), `ConfigSnapshot.get(key)`.
- **s27**: `Settings.smtp`, `Settings.env`.
- **s04**: `Permission.REPORTS_READ`, `require_permission`, `UowFactoryDep`.
- **s02**: `BaseRepository`, `UnitOfWork.repo`, `JsonDoc`, `UtcDateTime`, `IdentityPk`, `Page`, `Clock`, `WorkItemHistory`.

## Interfaces provided (pinned)

```python
# cashapp/services/notifications/channel.py
ChannelName = Literal["email", "teams"]
class ChannelSendError(Exception):
    channel: ChannelName; reason: str          # reason: exception class + short message; never the body or the address list
class NotificationChannel(Protocol):
    name: ChannelName
    async def send(self, recipients: Sequence[str], subject: str, body_text: str,
                   body_html: str | None) -> None: ...      # raises ChannelSendError
Channels = Mapping[ChannelName, NotificationChannel]
def build_channels(settings: Settings) -> Channels
    # env == "local" -> {"email": FakeChannel("email"), "teams": FakeChannel("teams")}
    # else: "email" -> SmtpEmailChannel(settings.smtp) when settings.smtp is not None; "teams" -> TeamsWebhookChannel()
    # A channel missing here makes its sends "suppressed" (error "channel_not_configured").

# cashapp/integrations/email/smtp.py
class SmtpEmailChannel:                       # implements NotificationChannel, name = "email"
    def __init__(self, smtp: SmtpSettings, *, timeout_seconds: float = 30.0,
                 smtp_factory: Callable[..., smtplib.SMTP] | None = None) -> None
    async def send(self, recipients, subject, body_text, body_html) -> None
    async def send_message(self, message: email.message.EmailMessage) -> None   # used by send_report_email
    # port 465 -> SMTP_SSL; else SMTP + starttls(ssl.create_default_context()); login(username, password.get_secret_value());
    # From = smtp.from_address; To = recipients; multipart/alternative when body_html; run in asyncio.to_thread.

# cashapp/integrations/email/teams_webhook.py
class TeamsWebhookChannel:                    # name = "teams"; recipients are webhook URLs
    def __init__(self, client: httpx.AsyncClient | None = None, *, timeout_seconds: float = 10.0) -> None
    async def send(self, recipients, subject, body_text, body_html) -> None
    # POST {"text": f"**{subject}**\n\n{body_text}"} per URL; non-2xx/timeout -> ChannelSendError

# cashapp/integrations/email/fake.py
@dataclass(frozen=True, slots=True)
class SentMessage: channel: str; recipients: tuple[str, ...]; subject: str; body_text: str; body_html: str | None
    ; attachments: tuple[tuple[str, bytes, str], ...] = ()
class FakeChannel:
    def __init__(self, name: ChannelName = "email", *, fail_with: Exception | None = None) -> None
    sent: list[SentMessage]
    async def send(...) -> None               # records, or raises ChannelSendError(fail_with)

# cashapp/services/notifications/render.py
SYSTEM_SUMMARY_KINDS: Final = frozenset({"dlq_growth", "outage"})   # summaries built by s42's own sources (counts only)
MAX_LISTED_ITEMS: Final = 200
@dataclass(frozen=True, slots=True)
class RenderedMessage: subject: str; body_text: str; body_html: str; item_ids: tuple[int, ...]
def render_batch(kind: str, events: Sequence[NotifyEvent], *, window_seconds: int, env_label: str,
                 app_base_url: str | None) -> RenderedMessage

# cashapp/services/notifications/batcher.py
@dataclass(frozen=True, slots=True)
class Batch: kind: str; events: tuple[NotifyEvent, ...]; severity: str  # max severity in the batch
class NotificationBatcher:
    def __init__(self, *, window_seconds: int) -> None
    window_seconds: int                       # mutable; refreshed from config before each add/flush
    def add(self, event: NotifyEvent, now: datetime) -> Batch | None   # returns a batch to send now (critical leading edge) else None
    def due(self, now: datetime) -> list[Batch]                         # windows that have elapsed
    def next_deadline(self) -> datetime | None
    def drain_all(self) -> list[Batch]                                   # shutdown

# cashapp/services/notifications/dispatcher.py
NotificationStatus = Literal["sent", "failed", "suppressed"]
@dataclass(frozen=True, slots=True)
class DispatchResult: channel: str; status: NotificationStatus; log_id: int
class NotificationDispatcher:
    def __init__(self, channels: Channels, *, clock: Clock, env_label: str) -> None
    async def dispatch(self, uow: UnitOfWork, batch: Batch, config: ConfigSnapshot) -> list[DispatchResult]
        # one NOTIFICATION_LOG row per configured channel (or one "suppressed" row, channel "none", when the kind
        # has no recipients). Writes rows, flushes, never commits (the caller commits).

# cashapp/services/notifications/emit.py
NOTIFY_TOPIC_NAME: Final = "notify"
def notify_topic() -> str                     # default_namer().named(NOTIFY_TOPIC_NAME)
async def emit_notification(uow: UnitOfWork, event: NotifyEvent, *, clock: Clock | None = None) -> None
    # enqueue(uow, topic=notify_topic(), key=event.kind, payload=event) — key is the KIND so one kind stays on one partition

# cashapp/services/notifications/sources.py
class DlqGrowthSource:
    def __init__(self) -> None                # last_notified: dict[Stage, int] starts at 0 per process
    async def check(self, uow: UnitOfWork, health: Mapping[Stage, StageBusHealth], *, now: datetime,
                    window_seconds: int, clock: Clock) -> NotifyEvent | None
class OutageSource:
    def __init__(self) -> None
    async def check(self, uow: UnitOfWork, *, now: datetime, threshold: int, window_seconds: int,
                    clock: Clock) -> NotifyEvent | None
class NotificationSourcesHook:                # implements s30 HealthTickHook
    async def on_tick(self, container: Container, now: datetime) -> None
        # one config snapshot; BusHealth via container.resolve(BusHealth); one UoW; emits 0..2 events; commits

# cashapp/services/notifications/reports.py   (consumed by s41)
Attachment = tuple[str, bytes, str]           # (filename, content, content_type)
async def send_report_email(recipients: Sequence[str], subject: str, body: str,
                            attachments: Sequence[Attachment] = (), *,
                            body_html: str | None = None,
                            channel: SmtpEmailChannel | FakeChannel | None = None,
                            uow: UnitOfWork | None = None, kind: str = "report",
                            clock: Clock | None = None) -> None
    # channel None -> SmtpEmailChannel(get_settings().smtp) (SettingsError-like ChannelSendError("smtp_not_configured") when None).
    # When uow is given, writes one NOTIFICATION_LOG row (kind, channel "email", status sent|failed; flush only).
    # Re-raises ChannelSendError after logging a failure. Empty recipients -> "suppressed" row (when uow) and return.

# cashapp/services/notifications/log_query.py
class NotificationLogService:
    async def list_log(self, uow: UnitOfWork, *, kind: str | None, from_: datetime | None, to: datetime | None,
                       offset: int = 0, limit: int = 50) -> Page[NotificationLog]

# cashapp/data/repositories/notifications.py
class NotificationLogRepository(BaseRepository[NotificationLog]):
    async def search(self, *, kind: str | None, from_: datetime | None, to: datetime | None,
                     offset: int, limit: int) -> Page[NotificationLog]          # sent_at DESC, id DESC
class TransientErrorRepository(BaseRepository[WorkItemHistory]):
    async def count_since(self, codes: Collection[ErrorCode], since: datetime) -> int
        # COUNT(*) FROM work_item_history WHERE error_code IN codes AND at >= since

# cashapp/stations/notify/consumer.py
class NotifyConsumer:                         # Runnable
    def __init__(self, *, bus: EventBus, group: str, uow_factory: UowFactory, config: RuntimeConfig,
                 clock: Clock, dispatcher: NotificationDispatcher, topic: str | None = None) -> None
    @classmethod
    def build(cls, container: Container) -> "NotifyConsumer"
        # channels: container.resolve(Channels-key) if registered (LookupError -> build_channels(container.settings));
        # group = container.settings.streaming.consumer_group (never suffixed)
    async def handle_delivery(self, delivery: Delivery) -> None   # parse, dedupe, buffer or send now (tests call directly)
    async def flush_due(self) -> int                               # send every elapsed window; returns batches sent
    async def run(self, stop: asyncio.Event) -> None
    def state(self) -> RoleState

# cashapp/stations/notify/__init__.py
ROLE: RoleSpec = RoleSpec("notify", "consumer", NotifyConsumer.build)
```

### HTTP contract (for s31 typing, s41 reports)

`GET /notifications/log?kind=&from=&to=&offset=0&limit=50` (`reports:read`). The `from` query parameter is aliased to `from_`.

- **Success:** `200 NotificationLogPage{items: NotificationLogOut[], total, offset, limit}`, newest first.
- **`NotificationLogOut`:** `{id, kind, severity, channel, recipients: list[str], subject, event_ids: list[str], item_count, sent_at, status: "sent"|"failed"|"suppressed", error: str|null}`.
- **Limits:** `limit` is 1..200 and `offset` is ≥ 0. Values outside those ranges get the framework 422.
- **Errors:**
  - `from > to` → 422 `invalid_range` (s01 `ApiError`).
  - Missing `reports:read` → 403, from s04.

## Migrations

- **Revision:** `api/alembic/versions/s42_notification_log.py`, `revision = "s42_notification_log"`. It's hand-written.
- **Expected parent:** the Alembic head when this merges, which is the latest wave-2 to wave-4 revision (for example s36's ledger or s45's). The merger re-points `down_revision` and checks that `alembic heads` returns exactly one head.
- **Table `notification_log`:**

  | Column | Type |
  |---|---|
  | `ID` | identity PK (`PK_NOTIFICATION_LOG`) |
  | `KIND` | `VARCHAR2(40) NOT NULL` |
  | `SEVERITY` | `VARCHAR2(20) NOT NULL` |
  | `CHANNEL` | `VARCHAR2(20) NOT NULL` (`email`, `teams` or `none`) |
  | `RECIPIENTS` | `JSON NOT NULL` (list of str; webhooks stored as `teams:<sha256[:12]>`, never the URL) |
  | `SUBJECT` | `VARCHAR2(400) NOT NULL` |
  | `EVENT_IDS` | `JSON NOT NULL` (list of UUID str) |
  | `ITEM_COUNT` | `NUMBER(10) NOT NULL` |
  | `SENT_AT` | `TIMESTAMP WITH TIME ZONE NOT NULL` |
  | `STATUS` | `VARCHAR2(20) NOT NULL` (no CHECK, per s02's enum rule) |
  | `ERROR` | `VARCHAR2(2000) NULL` |

- **Index:** `IX_NOTIFICATION_LOG_KIND_AT (KIND, SENT_AT)`. Queries filtered only by time use a second index, `IX_NOTIFICATION_LOG_AT (SENT_AT)`.
- **Downgrade:** drops the indexes, then the table.
- **Where it runs:** DEV ATP only.

## Design

### Consumer and batching (AC3)

- **Subscribe and parse.**
  - `run` subscribes to `notify_topic()` with the environment's consumer group.
  - A reader task feeds `handle_delivery`.
  - A flush task waits on `asyncio.wait_for(changed.wait(), timeout=until(next_deadline))` and calls `flush_due`.
  - `handle_delivery` parses `NotifyEvent.model_validate_json`. If it's malformed, it logs (offset only) and commits.
- **Dedupe.** An `event_id` already seen in this process (bounded LRU of 10,000) is committed and skipped.
- **Window logic (`NotificationBatcher`)**, per kind:
  1. The first event opens a window at `now`, and its deadline is `now + window_seconds`.
  2. Later events of that kind join the open window.
  3. A `critical` event sends immediately, together with anything already buffered for that kind, but only if no message for that kind went out in the last `window_seconds`. Otherwise it joins the buffer, which then sends at the deadline.
  4. After any send, `last_sent_at[kind] = now`, and the next window can't flush before `last_sent_at + window`.

  This guarantees at most one message per kind per window. The window is re-read from `config.notifications().batch_window_seconds` on every add and every flush.
- **Commit order.** Deliveries are held with their batch. After `dispatcher.dispatch(uow, batch, cfg)` and `uow.commit()`, every delivery in the batch is committed. s03's contiguous watermark makes out-of-order commits safe. On a crash, uncommitted events are redelivered and re-batched, which is at least once (see Risks).
- **Shutdown.** On stop, `drain_all()` flushes every open window before returning.

### Rendering (AC3, AC5)

- **Subject.** Template: `[CashApp {ENV}] {n} items escalated in the last {window_minutes} minutes`, where `ENV` is `settings.env` upper-cased.
  - Kind-specific subjects: `dlq_growth`: "Dead-letter queue grew", `outage`: "Possible outage: {code} errors", `budget_exceeded`: "Daily LLM budget exceeded". Any unknown kind gets "{n} {kind} events".
- **Body, one line per event:**
  - columns: `item <id>`, `<error_code>`, `<occurred_at ISO>` and the link `{app_base_url}/exceptions?item=<id>`. When `app_base_url` isn't configured, the link is the relative `/exceptions?item=<id>`.
  - at most 200 lines, then "and N more".
- **Summaries.** `event.summary` is rendered **only** for `SYSTEM_SUMMARY_KINDS`, whose summaries s42's own sources build from stage names and counts. For `item_escalated`, `budget_exceeded` and unknown kinds the summary is never rendered, because it may hold remittance text or payer names.
- **HTML.** The HTML body is the same content, `html.escape`d.

### Dispatcher (AC2, AC5)

- **Recipients.** They come from `cfg.notifications().recipients[kind]`, a channel → list map.
  - No entry, or every list empty: one `suppressed` row with channel `none` and error `no_recipients`.
  - A channel that's configured for the kind but has no implementation in `Channels` (for example SMTP settings missing, or Teams unset): a `suppressed` row with error `channel_not_configured`.
- **Sending.** Each channel sends at most 2 times, 2 s apart (a module constant). A second failure writes a `failed` row with `ChannelSendError.reason` truncated to 2000 characters, and the consumer carries on. A notification failure never blocks the queue.
- **Every attempt writes a row** (sent, failed or suppressed), with `EVENT_IDS`, `ITEM_COUNT` (distinct non-null work item ids, else the number of events), `SEVERITY` (the batch maximum) and `SENT_AT` set to `clock.now()`.

### Sources (AC4), run in the s30 health tick

- **DLQ growth (`DlqGrowthSource`).**
  - **Trigger:** from `BusHealth.snapshot()`, a stage whose `dlq_depth` is above `last_notified[stage]` (an unknown depth, -1, is skipped).
  - **Event:** one `NotifyEvent(kind="dlq_growth", severity="warning", summary="<stage>: +<delta> (now <depth>); …")` covering all stages that grew.
  - **Afterwards:** `last_notified` is updated. The source then emits nothing more for `window_seconds`, so growth inside the window is reported at the next tick after it ends.
  - **Restart:** `last_notified` starts at 0, so after a restart a DLQ that isn't empty is reported once.
- **Outage (`OutageSource`).**
  - **Trigger:** `TransientErrorRepository.count_since({FUSION_TRANSIENT, LLM_TRANSIENT}, now - outage_window_seconds)`, counted per code, reaching or exceeding `notifications.outage_threshold`.
  - **Event:** `NotifyEvent(kind="outage", severity="critical", error_code=<worst code>, summary="<code>: <n> in <m> min")`.
  - **Dedupe:** at most once per `window_seconds` per process.
- **Emitting.** Both sources emit through `emit_notification` (the outbox) inside the hook's UoW, then commit.
- **Multiple processes.** Every worker process runs the hook, so two processes can emit duplicates. The consumer's per-kind window collapses them into one message.

### API (AC6)

The router depends on `require_permission(Permission.REPORTS_READ)` and `UowFactoryDep`. It calls `NotificationLogService.list_log` and maps the rows to `NotificationLogOut`. It never returns an ORM model.

## TEST PLAN (written and run in step 5 only)

Unit tests run on aiosqlite using s02's `uow` / `uow_factory` fixtures, a `FrozenClock`, s28's `make_runtime_config`, s03's `InMemoryEventBus` and `FakeChannel`. `[integration]` tests run against aiosqlite by default. The `-m atp` variant runs against DEV ATP when credentials exist.

Support: `api/tests/support/notifications.py` provides:
- `make_notify_event(kind="item_escalated", severity="warning", work_item_id=1, error_code=ErrorCode.AGED_OUT, summary="…", occurred_at=…)`
- `publish_notify(bus, event)`
- `make_notify_consumer(uow_factory, bus, clock, channels, config_overrides)`

| AC | Test (file::name) |
|---|---|
| 1 | `api/tests/integration/test_notification_log_migration.py::test_revision_creates_notification_log_with_all_columns` (upgrade to `s42_notification_log`; inspector lists ID, KIND, SEVERITY, CHANNEL, RECIPIENTS, SUBJECT, EVENT_IDS, ITEM_COUNT, SENT_AT, STATUS, ERROR; downgrade drops it) |
| 1 | `…::test_single_alembic_head` |
| 1 | `api/tests/unit/data/test_notification_log_repo.py::test_add_and_roundtrip_json_columns` (lists round-trip; status free string, no CHECK) |
| 2 | `api/tests/unit/notifications/test_channels.py::test_fake_channel_satisfies_protocol_and_records` |
| 2 | `…::test_smtp_channel_starttls_login_and_multipart` (stub `smtp_factory`: `starttls` called with an SSL context, `login(username, secret)`, `send_message` with From/To/Subject, text + html alternatives) |
| 2 | `…::test_smtp_channel_port_465_uses_smtp_ssl` |
| 2 | `…::test_smtp_channel_error_raises_channel_send_error_without_body` |
| 2 | `…::test_teams_webhook_posts_json_and_maps_non_2xx` (respx: 200 ok; 500 → `ChannelSendError`) |
| 2 | `…::test_build_channels_local_fake_prod_real_and_missing_smtp` |
| 2 | `api/tests/unit/notifications/test_dispatcher.py::test_recipients_routed_per_kind_and_channel` (config `{"item_escalated": {"email": ["a@x"], "teams": ["https://hook"]}}` → both channels called) |
| 3 | `api/tests/integration/test_notify_consumer.py::test_fifty_escalations_in_window_send_one_message` (50 events, `flush_due` before the deadline → 0 sent; after → exactly 1 message whose subject says "50 items escalated in the last 5 minutes" and whose body lists 50 ids, codes and `/exceptions?item=<id>` links) |
| 3 | `…::test_critical_outage_sends_immediately` |
| 3 | `…::test_second_critical_within_window_is_batched_not_sent` |
| 3 | `…::test_kinds_batched_independently` |
| 3 | `…::test_offsets_committed_only_after_log_rows_committed` (bus `reset_group` before the flush redelivers; after the flush nothing is redelivered) |
| 3 | `…::test_duplicate_event_id_ignored` |
| 3 | `…::test_malformed_event_committed_and_skipped` |
| 3 | `…::test_stop_drains_open_windows` |
| 3 | `api/tests/unit/notifications/test_batcher.py::test_at_most_one_message_per_kind_per_window` (property over random arrival times) |
| 3 | `…::test_window_reread_from_config` |
| 3 | `api/tests/unit/notifications/test_role.py::test_notify_role_discovered` (s30 `discover_roles` finds `notify`, kind consumer) |
| 4 | `api/tests/unit/notifications/test_sources.py::test_dlq_growth_emits_once_on_increase` (snapshot depth 0→3 → one `dlq_growth` outbox row on the notify topic; 3→3 → none) |
| 4 | `…::test_dlq_growth_deduplicated_within_window` (3→5 inside the window → none; after the window → one) |
| 4 | `…::test_dlq_unknown_depth_ignored` |
| 4 | `…::test_outage_above_threshold_emits_critical` (11 `FUSION_TRANSIENT` history rows in 5 min with threshold 10 → one critical `outage` event; 9 rows → none; rows older than the window are not counted) |
| 4 | `…::test_outage_counts_llm_transient` |
| 4 | `…::test_outage_deduplicated_within_window` |
| 4 | `…::test_hook_registered_in_health_tick_hooks` |
| 5 | `api/tests/unit/notifications/test_dispatcher.py::test_every_send_writes_log_row_sent` |
| 5 | `…::test_failure_writes_failed_row_with_error_after_retry` |
| 5 | `…::test_no_recipients_writes_suppressed_row` |
| 5 | `…::test_missing_channel_writes_suppressed_channel_not_configured` |
| 5 | `…::test_teams_url_never_stored_in_recipients` |
| 5 | `api/tests/unit/notifications/test_render.py::test_body_contains_no_remittance_content_sentinel` (summary `"SENTINEL_PAYER_ACME 9999.99 INV-SENTINEL"` on `item_escalated` and `budget_exceeded` events → sentinel absent from subject, text, html, every log row and captured logs; ids, codes and counts present) |
| 5 | `…::test_system_kind_summary_rendered` |
| 5 | `…::test_listing_capped_at_200_with_more_line` |
| 5 | `…::test_links_absolute_when_base_url_configured_else_relative` |
| 6 | `api/tests/api/test_notifications_router.py::test_log_paged_newest_first` |
| 6 | `…::test_filters_kind_from_to` |
| 6 | `…::test_requires_reports_read` (no permission → 403 error envelope) |
| 6 | `…::test_from_after_to_is_422_invalid_range` |
| 7 | `api/tests/unit/notifications/test_reports.py::test_send_report_email_with_attachments` (FakeChannel/stub SMTP: the attachment's filename, bytes and content type preserved on the `EmailMessage`) |
| 7 | `…::test_send_report_email_logs_row_when_uow_given` |
| 7 | `…::test_send_report_email_smtp_not_configured_raises` |

## Assumptions (deviations logged)

- **The `NotifyEvent` shape comes from s18's story AC5**, because s18's plan wasn't written when this was planned. If s18 pins different field names, only `render.py`, `sources.py` and the test support change.
- **`emit_notification`:** if s18 already exports a notify-emit helper, `sources.py` uses it and `emit.py` keeps only `notify_topic()` (non-negotiable 7). s42 sets `key=kind`. If s18 keys by work item id instead, see Risks.
- **The DLQ check runs only on the s30 health tick,** not after each outbox relay batch. The relay is s03's file. A 30-second tick is well inside any batch window.
- **The outage counter comes from the database, not from in-process metrics.** It counts `WORK_ITEM_HISTORY` rows with `error_code` in `{FUSION_TRANSIENT, LLM_TRANSIENT}`; s03 and s18 record every failed attempt there. s29's `Metrics` exposes no readable counter outside `InMemoryMetrics`, and a per-process counter would miss the other workers. Transients that the client retried successfully on its own aren't outages and don't count.
- **New config keys:** `notifications.outage_threshold` (10), `notifications.outage_window_seconds` (300) and `notifications.app_base_url` (None). The story fixed "5 minutes" and didn't name the threshold or the base URL. Email links have to be absolute.
- **Teams is off by default:** it's enabled only when a kind lists `teams` webhooks in `notifications.recipients`. Webhook URLs sit in the configuration database as plain values, and the log stores only a hash prefix.
- **SMTP uses stdlib `smtplib` in a thread,** because `aiosmtplib` isn't pinned and lockfiles are frozen after wave 0.
- **The consumer's flush timer isn't a poller.** It only drains events that have already arrived, and it never queries an external system.

## Risks

- **At-least-once delivery.** If the process crashes after a send but before the offset commit, the batch is redelivered and resent. The in-process event_id LRU doesn't survive a restart. That's acceptable for alerts.
- **Partitioning.** If s18 emits with a key other than `kind`, one kind can be spread across partitions, and two `notify` replicas could each send once per window. Mitigation: run `notify` as a single replica (s25/s44), or the merger aligns the key.
- **Config key type conflict.** s02 pinned `NOTIFICATIONS_RECIPIENTS` as a flat map and s28 as a nested one. The first coder to hit it fixes it, and the merger checks there's exactly one definition.
- **OCI Email Delivery** needs an approved sender (`smtp.from_address`) and SMTP credentials in Vault. **VERIFY** against live: endpoint `smtp.email.us-ashburn-1.oci.oraclecloud.com:587` with STARTTLS. Until then only the fake and stub tests run.
- **`ERROR` as a column name.** It's allowed in Oracle, but the merger should confirm it against s02's reserved-word check. The fallback is `ERROR_MESSAGE`, mapped to the same attribute.
- **Hook cost.** The hook runs in every worker process every 30 seconds, adding one COUNT query on `work_item_history (error_code, at)`. The existing index is `(work_item_id, at)`. If the plan shows a full scan, an index on `(error_code, at)` is a follow-up. It isn't added here, to keep this story to one table.
