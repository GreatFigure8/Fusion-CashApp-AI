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
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.money import CurrencyCode, MoneyStr


@cache
def _adapter(tp: Any) -> TypeAdapter[Any]:
    return TypeAdapter(tp)


@dataclass(frozen=True)
class ConfigKey[T]:
    name: str
    group: str
    type: Any
    default: T
    description: str
    admin_only_write: bool = True

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
    name: str, tp: Any, default: T, description: str, *, admin_only_write: bool = True
) -> ConfigKey[T]:
    return ConfigKey(
        name=name,
        group=name.split(".", 1)[0],
        type=tp,
        default=default,
        description=description,
        admin_only_write=admin_only_write,
    )


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

# --- mcp.* : the fusion-sql-mcp (Greenlight) connection (fusion-mcp-transport) ---------------
# Hot: the client reconnects when the connection settings change, so none needs a restart.
# TODO(merger): once db-stored-settings lands, pass secret_ref=True on MCP_CLIENT_SECRET_REF and
# use its SecretRef type; the pattern below is the same Vault secret OCID check.
_HttpsUrl = Annotated[str, StringConstraints(pattern=r"^(https://\S+)?$")]
_VaultSecretRef = Annotated[str, StringConstraints(pattern=r"^(vault:)?ocid1\.vaultsecret\.\S+$")]

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
    _VaultSecretRef | None,
    None,
    "OCI Vault secret (OCID) holding the MCP OAuth client secret; never the secret itself.",
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
    MCP_SERVER_URL,
    MCP_TOKEN_URL,
    MCP_CLIENT_ID,
    MCP_CLIENT_SECRET_REF,
    MCP_SCOPE,
    MCP_FUSION_SOURCE,
    MCP_TIMEOUT_SECONDS,
    MCP_MAX_ROWS,
)


def _build_registry() -> Mapping[str, ConfigKey[Any]]:
    registry: dict[str, ConfigKey[Any]] = {}
    for key in _ALL_KEYS:
        if key.name in registry:
            raise RuntimeError(f"duplicate config key {key.name}")
        # A bad default (for example a fable model id) must fail at import, not at runtime.
        key.validate(key.default)
        registry[key.name] = key
    return MappingProxyType(registry)


CONFIG_KEYS: Mapping[str, ConfigKey[Any]] = _build_registry()


def group_keys(group: str) -> tuple[ConfigKey[Any], ...]:
    """All keys whose name starts with ``<group>.``, in registry order."""
    return tuple(key for key in CONFIG_KEYS.values() if key.group == group)
