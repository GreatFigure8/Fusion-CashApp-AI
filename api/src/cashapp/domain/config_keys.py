"""The registry of runtime configuration keys, their types and their defaults.

Defined once here; the runtime config service (s28) stores and serves values for these keys and
every consumer imports the constant it needs.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

from cashapp.domain.engine import Station
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.money import CurrencyCode, MoneyStr


@cache
def _adapter(tp: Any) -> TypeAdapter[Any]:
    return TypeAdapter(tp)


@dataclass(frozen=True)
class GroupSpec:
    label: str
    description: str
    order: int


@dataclass(frozen=True)
class ConfigKey[T]:
    name: str
    group: str
    type: Any
    default: T
    description: str
    admin_only_write: bool = True
    restart_required: bool = False
    secret_ref: bool = False

    def validate(self, value: object) -> T:
        result: T = _adapter(self.type).validate_python(value)
        return result

    def dump(self, value: T) -> Any:
        """JSON-compatible form of a value, as stored in the database."""
        return _adapter(self.type).dump_python(value, mode="json")


class ModelRole(BaseModel, frozen=True):
    """Which model plays a role, at what effort, with what timeout."""

    model_id: str
    effort: Literal["low", "medium", "high", "max"] | None
    timeout_s: Annotated[int, Field(gt=0)]

    @field_validator("model_id")
    @classmethod
    def _no_fable(cls, value: str) -> str:
        # Fable models need 30-day retention; client remittance data must not be retained.
        if "fable" in value.lower():
            raise ValueError("Fable models are not allowed: zero data retention is required")
        return value


class BankFeeBand(BaseModel, frozen=True):
    currency: CurrencyCode | Literal["*"]
    min_fee: MoneyStr
    max_fee: MoneyStr


def _error_code_or_star(value: dict[str, int]) -> dict[str, int]:
    valid = {code.value for code in ErrorCode} | {"*"}
    unknown = sorted(set(value) - valid)
    if unknown:
        raise ValueError(f"unknown error code(s): {', '.join(unknown)}")
    return value


def _key[T](
    name: str,
    tp: Any,
    default: T,
    description: str,
    *,
    admin_only_write: bool = True,
    restart_required: bool = False,
    secret_ref: bool = False,
) -> ConfigKey[T]:
    return ConfigKey(
        name=name,
        group=name.split(".", 1)[0],
        type=tp,
        default=default,
        description=description,
        admin_only_write=admin_only_write,
        restart_required=restart_required,
        secret_ref=secret_ref,
    )


VAULT_SECRET_OCID_PATTERN = r"^ocid1\.vaultsecret\.oc1\.[a-z0-9-]+\.[a-z0-9]{20,}$"  # noqa: S105
SecretRef = Annotated[str, StringConstraints(pattern=VAULT_SECRET_OCID_PATTERN)]
"""A Vault secret OCID. A secret key never holds the secret itself, only this reference."""


class FusionTestData(BaseModel, frozen=True):
    business_unit: str
    transaction_type: str
    receipt_method: str
    bank_account: str


class FusionPod(BaseModel, frozen=True):
    base_url: str
    username: str
    password_ref: SecretRef
    is_production: bool = False
    testdata: FusionTestData | None = None
    mcp_source: str | None = None

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


def _lower_pod_keys(value: object) -> object:
    if isinstance(value, dict):
        return {str(name).lower(): item for name, item in value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return value


def _lower_name(value: object) -> object:
    return value.lower() if isinstance(value, str) else value


_FusionPods = Annotated[dict[str, FusionPod], BeforeValidator(_lower_pod_keys)]
_FusionPodName = Annotated[str, BeforeValidator(_lower_name)] | None
_OptStr = str | None
_OptSecret = SecretRef | None
_LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
_Port = Annotated[int, Field(ge=1, le=65535)]


_Seconds = Annotated[int, Field(gt=0)]
_Days = Annotated[int, Field(ge=0)]
_Unit = Annotated[float, Field(ge=0.0, le=1.0)]
_ByErrorCode = Annotated[dict[str, int], AfterValidator(_error_code_or_star)]
_OptionalDays = Annotated[int, Field(gt=0)] | None
_Cutover = Annotated[str, StringConstraints(pattern=r"^\d{2}:\d{2}$")]

INTAKE_POLL_INTERVAL_SECONDS = _key(
    "intake.poll_interval_seconds",
    _Seconds,
    300,
    "Seconds between intake poller runs (mailbox and drop folder).",
)
RECEIPT_WATCHER_POLL_INTERVAL_SECONDS = _key(
    "receipt_watcher.poll_interval_seconds",
    _Seconds,
    300,
    "Seconds between Fusion receipt watcher runs.",
)
MATCHING_DATE_WINDOW_DAYS = _key(
    "matching.date_window_days",
    _Days,
    5,
    "Days either side of the payment date in which a receipt date qualifies.",
)
MATCHING_TOLERANCES = _key(
    "matching.tolerances",
    dict[str, MoneyStr],
    {
        "USD": Decimal("0.10"),
        "EUR": Decimal("0.10"),
        "INR": Decimal("0.49"),
        "*": Decimal("0.10"),
    },
    "Per-currency amount tolerance for matching; '*' is the fallback.",
)
MATCHING_BANK_FEE_BANDS = _key(
    "matching.bank_fee_bands",
    list[BankFeeBand],
    [],
    "Bank-fee bands that explain a receipt shortfall, per currency.",
)
MATCHING_SCORER_WEIGHTS = _key(
    "matching.scorer_weights",
    dict[str, float],
    dict[str, float](),
    "Receipt scorer feature weights (empty means scorer defaults).",
)
MATCHING_MIN_SCORE = _key(
    "matching.min_score", float, 0.0, "Minimum receipt score to accept a match."
)
RETRIES_MAX_ATTEMPTS = _key(
    "retries.max_attempts",
    _ByErrorCode,
    {"*": 3},
    "Maximum auto-fix attempts per error code; '*' is the fallback.",
)
RETRIES_BACKOFF_SECONDS = _key(
    "retries.backoff_seconds",
    list[Annotated[int, Field(ge=0)]],
    [30, 120, 600],
    "Backoff in seconds before each successive retry.",
)
AGING_AWAITING_RECEIPT_MAX_DAYS = _key(
    "aging.awaiting_receipt_max_days",
    _Days,
    30,
    "Days an item may wait in AWAITING_RECEIPT before it is escalated.",
)
ESCALATION_MIN_EXTRACTION_CONFIDENCE = _key(
    "escalation.min_extraction_confidence",
    _Unit,
    0.8,
    "Extraction confidence below this value is treated as low confidence.",
)
MODELS_READER_A = _key(
    "models.reader_a",
    ModelRole,
    ModelRole(model_id="claude-opus-5-5", effort="high", timeout_s=120),
    "Reader A: reads the artifact and extracts the remittance.",
)
MODELS_READER_B = _key(
    "models.reader_b",
    ModelRole,
    ModelRole(model_id="cohere.command-a-vision", effort=None, timeout_s=120),
    "Reader B: independent second reader (OCI Generative AI, dedicated cluster).",
)
MODELS_ADJUDICATOR = _key(
    "models.adjudicator",
    ModelRole,
    ModelRole(model_id="claude-opus-5-5", effort="medium", timeout_s=120),
    "Adjudicator: compares the two readers and decides per field and per line.",
)
MODELS_WORKHORSE = _key(
    "models.workhorse",
    ModelRole,
    ModelRole(model_id="claude-haiku-5-5", effort="low", timeout_s=60),
    "Workhorse: triage, chat, auto-fix reasoning, summaries and notes.",
)
EXTRACTION_FANIN_TIMEOUT_SECONDS = _key(
    "extraction.fanin_timeout_seconds", _Seconds, 180, "How long the fan-in waits for both readers."
)
CONCURRENCY_PER_STAGE = _key(
    "concurrency.per_stage",
    dict[str, int],
    {"*": 4},
    "Concurrent items per stage; '*' is the fallback.",
)
CONCURRENCY_APPLY_PER_RECEIPT = _key(
    "concurrency.apply_per_receipt", _Seconds, 1, "Concurrent Fusion applies per receipt."
)
LOCKS_LEASE_MINUTES = _key(
    "locks.lease_minutes", _Seconds, 30, "Lease length of a person's lock on an item."
)
BACKLOG_RATE_LIMIT_PER_MINUTE = _key(
    "backlog.rate_limit_per_minute",
    _Seconds,
    20,
    "Backlog items released into the pipeline per minute.",
)
RETENTION_RAW_ARTIFACT_DAYS = _key(
    "retention.raw_artifact_days",
    _OptionalDays,
    None,
    "Days to keep raw artifacts; empty keeps them forever.",
)
RETENTION_EXTRACTION_DAYS = _key(
    "retention.extraction_days",
    _OptionalDays,
    None,
    "Days to keep extraction data; empty keeps it forever.",
)
RETENTION_HISTORY_PAYLOAD_DAYS = _key(
    "retention.history_payload_days",
    _OptionalDays,
    None,
    "Days to keep history payloads; empty keeps them forever.",
)
BUDGET_DAILY_USD = _key(
    "budget.daily_usd",
    MoneyStr | None,
    None,
    "Daily LLM spend ceiling in USD; empty means no ceiling.",
)
NOTIFICATIONS_RECIPIENTS = _key(
    "notifications.recipients",
    dict[str, list[str]],
    dict[str, list[str]](),
    "Notification recipients by channel or event.",
)
NOTIFICATIONS_BATCH_WINDOW_SECONDS = _key(
    "notifications.batch_window_seconds",
    _Seconds,
    300,
    "Window in which notifications are batched.",
)
NOTIFICATIONS_OUTAGE_THRESHOLD = _key(
    "notifications.outage_threshold",
    Annotated[int, Field(ge=1)],
    10,
    "Transient Fusion or LLM errors within the outage window that count as an outage.",
)
NOTIFICATIONS_OUTAGE_WINDOW_SECONDS = _key(
    "notifications.outage_window_seconds",
    Annotated[int, Field(ge=60)],
    300,
    "Window in which transient errors are counted for outage detection.",
)
NOTIFICATIONS_APP_BASE_URL = _key(
    "notifications.app_base_url",
    str | None,
    None,
    "Base URL of the web app, used for links in notifications; empty gives relative links.",
)
REPORTS_DAILY_SUMMARY_CUTOVER = _key(
    "reports.daily_summary_cutover",
    _Cutover,
    "07:00",
    "Local time (HH:MM) at which the daily summary day rolls over.",
)
DISCOUNT_ENABLED = _key(
    "discount.enabled", bool, False, "Take earned discounts when the remittance references them."
)
FUSION_RECEIPT_NOTE_MAX_CHARS = _key(
    "fusion.receipt_note_max_chars",
    Annotated[int, Field(ge=60, le=2000)],
    240,
    "Maximum characters of the note written to a Fusion receipt's Comments field.",
)

CHAT_CONFIRM_TTL_SECONDS = _key(
    "chat.confirm_ttl_seconds",
    Annotated[int, Field(ge=60, le=3600)],
    600,
    "Seconds a proposed assistant change stays open for the person to confirm.",
)
CHAT_MAX_TOOL_CALLS_PER_TURN = _key(
    "chat.max_tool_calls_per_turn",
    Annotated[int, Field(ge=1, le=20)],
    8,
    "Most tool calls the assistant may make in one reply.",
)

# --- deploy settings moved off the environment (db-stored-settings) -----------------------------

STREAMING_BOOTSTRAP_SERVERS: ConfigKey[str | None] = _key(
    "streaming.bootstrap_servers",
    _OptStr,
    None,
    "Kafka-compatible bootstrap servers of OCI Streaming.",
    restart_required=True,
)
STREAMING_SASL_USERNAME: ConfigKey[str | None] = _key(
    "streaming.sasl_username",
    _OptStr,
    None,
    "SASL user for OCI Streaming (tenancy/user/stream pool).",
    restart_required=True,
)
STREAMING_SASL_PASSWORD_REF: ConfigKey[str | None] = _key(
    "streaming.sasl_password_ref",
    _OptSecret,
    None,
    "Vault secret OCID of the OCI Streaming auth token.",
    restart_required=True,
    secret_ref=True,
)
STREAMING_TOPIC_PREFIX = _key(
    "streaming.topic_prefix",
    str,
    "cashapp",
    "Prefix of every topic name.",
    restart_required=True,
)
STREAMING_CONSUMER_GROUP: ConfigKey[str | None] = _key(
    "streaming.consumer_group",
    _OptStr,
    None,
    "Kafka consumer group of this environment. Never rename or reset it: offsets are lost.",
    restart_required=True,
)
OBJECT_STORAGE_NAMESPACE: ConfigKey[str | None] = _key(
    "object_storage.namespace",
    _OptStr,
    None,
    "OCI Object Storage namespace (region is fixed at us-ashburn-1).",
    restart_required=True,
)
OBJECT_STORAGE_BUCKET: ConfigKey[str | None] = _key(
    "object_storage.bucket",
    _OptStr,
    None,
    "OCI Object Storage bucket for raw artifacts.",
    restart_required=True,
)
ANTHROPIC_BASE_URL: ConfigKey[str | None] = _key(
    "anthropic.base_url",
    _OptStr,
    None,
    "Override of the Claude API base URL; empty uses the SDK default.",
    restart_required=True,
)
ANTHROPIC_API_KEY_REF: ConfigKey[str | None] = _key(
    "anthropic.api_key_ref",
    _OptSecret,
    None,
    "Vault secret OCID of the Claude API key (zero-retention organisation).",
    restart_required=True,
    secret_ref=True,
)
OCI_GENAI_ENDPOINT = _key(
    "oci_genai.endpoint",
    str,
    "https://inference.generativeai.us-ashburn-1.oci.oraclecloud.com",
    "OCI Generative AI inference endpoint (Ashburn).",
    restart_required=True,
)
OCI_GENAI_COMPARTMENT_OCID: ConfigKey[str | None] = _key(
    "oci_genai.compartment_ocid",
    _OptStr,
    None,
    "Compartment OCID used for Generative AI calls and metrics.",
    restart_required=True,
)
OCI_GENAI_DEDICATED_ENDPOINT_OCID: ConfigKey[str | None] = _key(
    "oci_genai.dedicated_endpoint_ocid",
    _OptStr,
    None,
    "OCID of the dedicated AI cluster endpoint that serves Reader B.",
    restart_required=True,
)
OCI_GENAI_DEDICATED_CLUSTER_OCID: ConfigKey[str | None] = _key(
    "oci_genai.dedicated_cluster_ocid",
    _OptStr,
    None,
    "OCID of the dedicated AI cluster, for utilisation metrics; empty turns the metric off.",
)
OCI_GENAI_CLUSTER_METRIC_NAMESPACE = _key(
    "oci_genai.cluster_metric_namespace",
    str,
    "oci_generativeai",
    "OCI Monitoring namespace of the cluster utilisation metric.",
)
OCI_GENAI_CLUSTER_METRIC_QUERY: ConfigKey[str | None] = _key(
    "oci_genai.cluster_metric_query",
    _OptStr,
    None,
    "MQL query template with a {cluster_ocid} placeholder; empty keeps the metric off.",
)
IDENTITY_ISSUER: ConfigKey[str | None] = _key(
    "identity.issuer",
    _OptStr,
    None,
    "Issuer of sign-in tokens (identity domain).",
    restart_required=True,
)
IDENTITY_JWKS_URL: ConfigKey[str | None] = _key(
    "identity.jwks_url",
    _OptStr,
    None,
    "JWKS URL used to verify token signatures.",
    restart_required=True,
)
IDENTITY_AUDIENCE: ConfigKey[str | None] = _key(
    "identity.audience",
    _OptStr,
    None,
    "Audience the API accepts in tokens.",
    restart_required=True,
)
IDENTITY_GROUPS_CLAIM = _key(
    "identity.groups_claim",
    str,
    "groups",
    "Token claim that carries the user's identity-domain groups.",
    restart_required=True,
)
FUSION_PODS = _key(
    "fusion.pods",
    _FusionPods,
    dict[str, FusionPod](),
    "Fusion pods by lower-case name: base URL, user, password secret OCID, test-data defaults.",
    restart_required=True,
)
FUSION_DEFAULT_POD: ConfigKey[str | None] = _key(
    "fusion.default_pod",
    _FusionPodName,
    None,
    "Name of the pod the pipeline uses; must be one of fusion.pods.",
    restart_required=True,
)
FUSION_WRITE_ENABLED = _key(
    "fusion.write_enabled",
    bool,
    False,
    "Master switch: when off, nothing is written to Fusion.",
)
FUSION_UNAPPLY_VERIFIED = _key(
    "fusion.unapply_verified",
    bool,
    False,
    "Set once a live probe has confirmed the unapply SOAP contract; gates reversal.",
)
FUSION_RELATIONSHIPS_REPORT_PATH: ConfigKey[str | None] = _key(
    "fusion.relationships_report_path",
    _OptStr,
    None,
    "BI Publisher report path that returns pay-on-behalf relationships.",
)
OBSERVABILITY_LOG_LEVEL: ConfigKey[Literal["DEBUG", "INFO", "WARNING", "ERROR"]] = _key(
    "observability.log_level",
    _LogLevel,
    "INFO",
    "Root log level.",
    restart_required=True,
)
OBSERVABILITY_OTLP_ENDPOINT: ConfigKey[str | None] = _key(
    "observability.otlp_endpoint",
    _OptStr,
    None,
    "OTLP endpoint for traces; empty turns tracing off.",
    restart_required=True,
)
OBSERVABILITY_OCI_MONITORING_NAMESPACE = _key(
    "observability.oci_monitoring_namespace",
    str,
    "cashapp",
    "OCI Monitoring namespace for custom metrics.",
    restart_required=True,
)
WORKER_SHUTDOWN_GRACE_SECONDS = _key(
    "worker.shutdown_grace_seconds",
    Annotated[int, Field(ge=1)],
    30,
    "Seconds a worker waits for in-flight work on shutdown.",
)
INTAKE_DROP_FOLDER: ConfigKey[str | None] = _key(
    "intake.drop_folder",
    _OptStr,
    None,
    "Folder the intake poller watches (also holds the local object store).",
    restart_required=True,
)
SMTP_HOST: ConfigKey[str | None] = _key(
    "smtp.host",
    _OptStr,
    None,
    "SMTP host; empty turns the email channel off.",
    restart_required=True,
)
SMTP_PORT = _key("smtp.port", _Port, 587, "SMTP port.", restart_required=True)
SMTP_USERNAME: ConfigKey[str | None] = _key(
    "smtp.username", _OptStr, None, "SMTP user.", restart_required=True
)
SMTP_FROM_ADDRESS: ConfigKey[str | None] = _key(
    "smtp.from_address",
    _OptStr,
    None,
    "From address of notification email.",
    restart_required=True,
)
SMTP_PASSWORD_REF: ConfigKey[str | None] = _key(
    "smtp.password_ref",
    _OptSecret,
    None,
    "Vault secret OCID of the SMTP password.",
    restart_required=True,
    secret_ref=True,
)

REQUIRED_KEYS: tuple[ConfigKey[Any], ...] = (
    STREAMING_BOOTSTRAP_SERVERS,
    STREAMING_SASL_USERNAME,
    STREAMING_SASL_PASSWORD_REF,
    STREAMING_CONSUMER_GROUP,
    OBJECT_STORAGE_NAMESPACE,
    OBJECT_STORAGE_BUCKET,
    ANTHROPIC_API_KEY_REF,
    OCI_GENAI_COMPARTMENT_OCID,
    OCI_GENAI_DEDICATED_ENDPOINT_OCID,
    IDENTITY_ISSUER,
    IDENTITY_JWKS_URL,
    IDENTITY_AUDIENCE,
    FUSION_PODS,
    FUSION_DEFAULT_POD,
    FUSION_RELATIONSHIPS_REPORT_PATH,
    INTAKE_DROP_FOLDER,
)
"""Keys whose default is empty but which every process needs; `RuntimeSettings.start` names
every one that is still empty."""

CONFIG_GROUPS: Mapping[str, GroupSpec] = MappingProxyType(
    {
        "intake": GroupSpec(
            "Pollers: intake", "Mailbox and drop-folder poller, and the drop folder.", 10
        ),
        "receipt_watcher": GroupSpec(
            "Pollers: receipt watcher", "Fusion receipt watcher timing.", 20
        ),
        "matching": GroupSpec("Matching", "Receipt and line matching rules and tolerances.", 30),
        "retries": GroupSpec("Auto-fix retries", "Attempt limits and backoff for auto-fix.", 40),
        "aging": GroupSpec("Aging", "How long items may wait before escalation.", 50),
        "escalation": GroupSpec("Escalation", "Thresholds that send an item to a person.", 60),
        "models": GroupSpec("Models", "Which model plays each role, at what effort.", 70),
        "extraction": GroupSpec("Extraction", "Extraction fan-in behaviour.", 80),
        "concurrency": GroupSpec("Concurrency", "Parallelism per stage and per receipt.", 90),
        "locks": GroupSpec("Locks", "Person lock lease on an item.", 100),
        "backlog": GroupSpec("Backlog", "Backlog release rate.", 110),
        "retention": GroupSpec("Retention", "How long data is kept.", 120),
        "budget": GroupSpec("Budget", "LLM spend ceiling.", 130),
        "notifications": GroupSpec(
            "Notifications", "Recipients, batching and outage detection.", 140
        ),
        "reports": GroupSpec("Reports", "Daily summary timing.", 150),
        "discount": GroupSpec("Discounts", "Discount-taking rules.", 160),
        "fusion": GroupSpec("Fusion", "Fusion pods, write switch and report paths.", 170),
        "streaming": GroupSpec("Event bus", "OCI Streaming connection and topics.", 180),
        "object_storage": GroupSpec("Object Storage", "Bucket that holds raw artifacts.", 190),
        "anthropic": GroupSpec("Claude API", "Anthropic API connection.", 200),
        "oci_genai": GroupSpec("OCI Generative AI", "Reader B endpoint and cluster metrics.", 210),
        "identity": GroupSpec("Sign-in", "Identity domain token validation.", 220),
        "observability": GroupSpec("Observability", "Logging, tracing and metrics.", 230),
        "worker": GroupSpec("Workers", "Worker shutdown behaviour.", 240),
        "smtp": GroupSpec("Email (SMTP)", "Outgoing email; empty host turns it off.", 250),
        "chat": GroupSpec("Assistant", "Assistant tool calls and confirmations.", 260),
        "mcp": GroupSpec("Fusion MCP", "Connection to the fusion-sql-mcp server.", 280),
        "engine": GroupSpec("Engine", "Paused and draining stations, engine status timing.", 270),
    }
)
ENGINE_PAUSED_STATIONS = _key(
    "engine.paused_stations",
    list[Station],
    list[Station](),
    "Stations held by a person: their consumers take no new delivery until resumed.",
)
ENGINE_DRAINING_STATIONS = _key(
    "engine.draining_stations",
    list[Station],
    list[Station](),
    "Stations being drained: paused, and reported drained once nothing is in flight.",
)
ENGINE_STATUS_CACHE_SECONDS = _key(
    "engine.status_cache_seconds",
    _Seconds,
    5,
    "How long one computed engine status is shared by every reader in a process.",
)
ENGINE_STREAM_TICK_SECONDS = _key(
    "engine.stream_tick_seconds",
    _Seconds,
    2,
    "How often an open engine stream checks whether the status changed.",
)
ENGINE_AUDIT_PAGE_SIZE = _key(
    "engine.audit_page_size",
    Annotated[int, Field(ge=1, le=200)],
    50,
    "Default page size of the engine audit log.",
)


# --- mcp.* : the fusion-sql-mcp (Greenlight) connection (fusion-mcp-transport) ---------------
# Hot: the client reconnects when the connection settings change, so none needs a restart.
_HttpsUrl = Annotated[str, StringConstraints(pattern=r"^(https://\S+)?$")]

MCP_SERVER_URL = _key(
    "mcp.server_url",
    _HttpsUrl,
    "",
    "Streamable HTTP endpoint of the fusion-sql-mcp server; empty means not configured.",
)
MCP_TOKEN_URL = _key(
    "mcp.token_url",
    _HttpsUrl,
    "",
    "OAuth token endpoint of the identity domain that issues the MCP client_credentials JWT.",
)
MCP_CLIENT_ID = _key(
    "mcp.client_id", str, "", "OAuth client id the cash app uses for the MCP server."
)
MCP_CLIENT_SECRET_REF = _key(
    "mcp.client_secret_ref",
    _OptSecret,
    None,
    "OCI Vault secret (OCID) holding the MCP OAuth client secret; never the secret itself.",
    secret_ref=True,
)
MCP_SCOPE = _key("mcp.scope", str, "greenlight/mcp", "OAuth scope requested for the MCP token.")
MCP_FUSION_SOURCE = _key(
    "mcp.fusion_source",
    str,
    "",
    "The MCP server's Fusion source label used when a pod has no mcp_source of its own.",
)
MCP_TIMEOUT_SECONDS = _key(
    "mcp.timeout_seconds",
    Annotated[int, Field(ge=1, le=600)],
    60,
    "Seconds before one MCP tool call is abandoned.",
)
MCP_MAX_ROWS = _key(
    "mcp.max_rows",
    Annotated[int, Field(ge=1, le=50000)],
    2000,
    "Row cap of the assistant's Fusion query tool and the page size of run_query.",
)

_ALL_KEYS: tuple[ConfigKey[Any], ...] = (
    INTAKE_POLL_INTERVAL_SECONDS,
    RECEIPT_WATCHER_POLL_INTERVAL_SECONDS,
    MATCHING_DATE_WINDOW_DAYS,
    MATCHING_TOLERANCES,
    MATCHING_BANK_FEE_BANDS,
    MATCHING_SCORER_WEIGHTS,
    MATCHING_MIN_SCORE,
    RETRIES_MAX_ATTEMPTS,
    RETRIES_BACKOFF_SECONDS,
    AGING_AWAITING_RECEIPT_MAX_DAYS,
    ESCALATION_MIN_EXTRACTION_CONFIDENCE,
    MODELS_READER_A,
    MODELS_READER_B,
    MODELS_ADJUDICATOR,
    MODELS_WORKHORSE,
    EXTRACTION_FANIN_TIMEOUT_SECONDS,
    CONCURRENCY_PER_STAGE,
    CONCURRENCY_APPLY_PER_RECEIPT,
    LOCKS_LEASE_MINUTES,
    BACKLOG_RATE_LIMIT_PER_MINUTE,
    RETENTION_RAW_ARTIFACT_DAYS,
    RETENTION_EXTRACTION_DAYS,
    RETENTION_HISTORY_PAYLOAD_DAYS,
    BUDGET_DAILY_USD,
    NOTIFICATIONS_RECIPIENTS,
    NOTIFICATIONS_BATCH_WINDOW_SECONDS,
    NOTIFICATIONS_OUTAGE_THRESHOLD,
    NOTIFICATIONS_OUTAGE_WINDOW_SECONDS,
    NOTIFICATIONS_APP_BASE_URL,
    REPORTS_DAILY_SUMMARY_CUTOVER,
    DISCOUNT_ENABLED,
    FUSION_RECEIPT_NOTE_MAX_CHARS,
    CHAT_CONFIRM_TTL_SECONDS,
    CHAT_MAX_TOOL_CALLS_PER_TURN,
    STREAMING_BOOTSTRAP_SERVERS,
    STREAMING_SASL_USERNAME,
    STREAMING_SASL_PASSWORD_REF,
    STREAMING_TOPIC_PREFIX,
    STREAMING_CONSUMER_GROUP,
    OBJECT_STORAGE_NAMESPACE,
    OBJECT_STORAGE_BUCKET,
    ANTHROPIC_BASE_URL,
    ANTHROPIC_API_KEY_REF,
    OCI_GENAI_ENDPOINT,
    OCI_GENAI_COMPARTMENT_OCID,
    OCI_GENAI_DEDICATED_ENDPOINT_OCID,
    OCI_GENAI_DEDICATED_CLUSTER_OCID,
    OCI_GENAI_CLUSTER_METRIC_NAMESPACE,
    OCI_GENAI_CLUSTER_METRIC_QUERY,
    IDENTITY_ISSUER,
    IDENTITY_JWKS_URL,
    IDENTITY_AUDIENCE,
    IDENTITY_GROUPS_CLAIM,
    FUSION_PODS,
    FUSION_DEFAULT_POD,
    FUSION_WRITE_ENABLED,
    FUSION_UNAPPLY_VERIFIED,
    FUSION_RELATIONSHIPS_REPORT_PATH,
    OBSERVABILITY_LOG_LEVEL,
    OBSERVABILITY_OTLP_ENDPOINT,
    OBSERVABILITY_OCI_MONITORING_NAMESPACE,
    WORKER_SHUTDOWN_GRACE_SECONDS,
    INTAKE_DROP_FOLDER,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_FROM_ADDRESS,
    SMTP_PASSWORD_REF,
    ENGINE_PAUSED_STATIONS,
    ENGINE_DRAINING_STATIONS,
    ENGINE_STATUS_CACHE_SECONDS,
    ENGINE_STREAM_TICK_SECONDS,
    ENGINE_AUDIT_PAGE_SIZE,
    MCP_SERVER_URL,
    MCP_TOKEN_URL,
    MCP_CLIENT_ID,
    MCP_CLIENT_SECRET_REF,
    MCP_SCOPE,
    MCP_FUSION_SOURCE,
    MCP_TIMEOUT_SECONDS,
    MCP_MAX_ROWS,
)


_SECRET_WORDS = ("password", "api_key", "secret", "token")


def _check_flags(key: ConfigKey[Any]) -> None:
    if key.group not in CONFIG_GROUPS:
        raise RuntimeError(f"config key {key.name} is in group {key.group!r} with no GroupSpec")
    if key.secret_ref:
        try:
            key.validate("not-a-vault-ocid")
        except ValueError:
            pass
        else:
            raise RuntimeError(f"secret key {key.name} must be typed SecretRef")
        if not key.name.endswith("_ref"):
            raise RuntimeError(f"secret_ref key {key.name} must be named *_ref")
    elif any(word in key.name for word in _SECRET_WORDS):
        raise RuntimeError(f"config key {key.name} looks secret but is not a secret_ref key")


def _build_registry() -> Mapping[str, ConfigKey[Any]]:
    registry: dict[str, ConfigKey[Any]] = {}
    for key in _ALL_KEYS:
        if key.name in registry:
            raise RuntimeError(f"duplicate config key {key.name}")
        # A bad default (for example a fable model id) must fail at import, not at runtime.
        key.validate(key.default)
        _check_flags(key)
        registry[key.name] = key
    return MappingProxyType(registry)


CONFIG_KEYS: Mapping[str, ConfigKey[Any]] = _build_registry()


def group_keys(group: str) -> tuple[ConfigKey[Any], ...]:
    """All keys whose name starts with ``<group>.``, in registry order."""
    return tuple(key for key in CONFIG_KEYS.values() if key.group == group)
