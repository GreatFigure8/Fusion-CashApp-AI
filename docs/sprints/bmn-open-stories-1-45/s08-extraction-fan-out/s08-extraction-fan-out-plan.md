# s08-extraction-fan-out: plan

Issue #8. Wave 2. Python only (no web files, no UI). Paths: `cashapp/` = `api/src/cashapp/`.

## Standards followed

- CLAUDE.md *Models: who does what*: Reader A = `claude-opus-5-5` (Anthropic SDK), Reader B = `cohere.command-a-vision` (OCI GenAI, `DedicatedServingMode`, Ashburn). Roles are not changed. Zero data retention: any model id containing `fable` (case-insensitive) is refused in the `AnthropicLlmClient` constructor (s02's `ModelRole` validator already blocks it in config; this is the second, independent guard).
- `claude-api` skill (Python): `client.messages.parse(model=, max_tokens=, system=, messages=, output_format=<PydanticModel>, output_config={"effort": ...})`, result in `response.parsed_output`; thinking is never sent as `disabled` and `budget_tokens` is never sent (both 400 on Opus 5.5; adaptive is the default); effort always set explicitly (Opus 5.5 default is `medium`); no `tool_choice`, no `tools`; `stop_reason == "refusal"` checked before `parsed_output` is read; no assistant prefill; no `temperature`/`top_p`/`top_k` (400 since 2026-10-21). PDFs go as `{"type":"document","source":{"type":"base64","media_type":"application/pdf","data":...}}`, images as `{"type":"image","source":{"type":"base64",...}}`, placed before the text block. Typed SDK exceptions chained most-specific first (`RateLimitError`, `InternalServerError`/`APIStatusError >= 500`, `APITimeoutError`, `APIConnectionError` → `LLM_TRANSIENT`; `BadRequestError`/other 4xx → `EXTRACTION_FAILED`-class `LlmError`). SDK `max_retries=0` (retries belong to the auto-fix engine so every attempt is recorded).
- `python-llm-features:building-llm-backed-features`: the field descriptions of `RemittanceExtraction` are prompt surface, so load-bearing wording lives in one constants module (`stations/extract/prompts.py`) that both the prompt and `Field(description=...)` import; one shared content limiter (`fit_parts`) used by every prompt path (both readers, s07, s09); live calls are marked `@pytest.mark.live` and deselected by default (s01 `addopts`); `confidence` is a per-field value produced by the reader, never a copied response-level score; config read through typed models (s28 `ModelsConfig`, `ExtractionConfig`), no hard-indexed dicts.
- `python-web-app:building-python-web-apps`: layering. Stations (business) use repositories via the UoW; only `data/` imports SQLAlchemy; the integration layer imports neither FastAPI nor SQLAlchemy. Pydantic v2 for schemas; `asyncio.to_thread` for the synchronous OCI SDK.
- research.md: exactly two real implementations behind `LlmClient` (Anthropic, OCI Cohere) plus one replay fake; the fake and the Cohere request shape are marked "unverified against live" until the `-m live` probe passes. Money as `MoneyStr` (s02), never float.
- CLAUDE.md conventions: prompts, artifacts and model output are never logged (only ids, token counts, status); spans `llm.reader_a` / `llm.reader_b` carry `work_item_id`, `model`, `input_tokens`, `output_tokens`, `latency_ms` (s29 sanitiser). Invoice numbers are strings end to end.

## Files to touch

All new. File-disjoint from other stories (owned dirs: `cashapp/integrations/llm/`, `cashapp/domain/extraction.py`, `cashapp/stations/extract/`, `cashapp/data/repositories/readings.py`, plus the model module and the one migration below).

| Path | Content |
|---|---|
| `cashapp/integrations/__init__.py` | empty, only if absent |
| `cashapp/integrations/llm/__init__.py` | re-exports the public names of `base.py` |
| `cashapp/integrations/llm/base.py` | `LlmClient` Protocol, `ContentPart` (`TextPart`, `ImagePart`, `PdfPart`), `LlmRequest`, `LlmUsage`, `LlmResult[T]`, `LlmErrorCode`, `LlmError`, `LlmClients`, `parts_digest` |
| `cashapp/integrations/llm/content.py` | `ArtifactPartRef`, `load_content_parts` (ObjectStore → `ContentPart`s; DOCX → text via python-docx; TABLE → CSV text), `fit_parts` (the single limiter) |
| `cashapp/integrations/llm/pdf.py` | `pdf_to_text_and_images(data, *, max_pages, max_images) -> PdfRendering` (pypdf text layer + embedded page images re-encoded to PNG via Pillow) |
| `cashapp/integrations/llm/anthropic_client.py` | `AnthropicLlmClient` |
| `cashapp/integrations/llm/oci_cohere_client.py` | `OciCohereLlmClient`, `CohereChatTransport` Protocol (seam over `GenerativeAiInferenceClient.chat`) |
| `cashapp/integrations/llm/fake.py` | `ReplayLlmClient`, `ScriptedStep`, `Recording` (test-support file owned here, lives in `src/` so s24 `--replay` can use it) |
| `cashapp/integrations/llm/factory.py` | `build_llm_clients(settings, config) -> LlmClients` |
| `cashapp/domain/extraction.py` | `SCHEMA_VERSION`, `SourceLocation`, `Extracted[T]`, `DateKind`, `DateCandidate`, `LineKind`, `ExtractedLine`, `RemittanceExtraction` |
| `cashapp/domain/extraction_text.py` | load-bearing field-description constants shared by the schema and the prompt |
| `cashapp/stations/__init__.py` | empty, only if absent |
| `cashapp/stations/extract/__init__.py` | exposes `ROLE` |
| `cashapp/stations/extract/prompts.py` | `PROMPT_VERSION = "1"`, `READER_SYSTEM_PROMPT`, field-description constants, `build_reader_request(...)`, `EXTRACT_MAX_TOKENS` |
| `cashapp/stations/extract/runner.py` | `ExtractRunner(StageRunner)`, `ReaderOutcome`, `build(container)`, `ROLE` |
| `cashapp/data/models/extraction_reading.py` | ORM `ExtractionReading`; enums `ReaderSlot`, `ReadingStatus` live in `cashapp/domain/extraction.py` |
| `cashapp/data/repositories/readings.py` | `ExtractionReadingRepository` |
| `api/alembic/versions/<rev>_s08_extraction_reading.py` | the one revision (see Migrations) |
| `api/tests/support/llm.py` | `scripted_llm(...)`, `make_extraction(**overrides)`, `make_llm_clients(...)` |
| `api/tests/fixtures/llm/README.md` + `api/tests/fixtures/llm/extract_synthetic_a.json`, `extract_synthetic_b.json` | recorded `LlmResult` fixtures (synthetic remittance, no client data) + "unverified against live" note |
| `api/tests/fixtures/artifacts/synthetic_remittance.pdf`, `synthetic_remittance.png` | synthetic inputs for the PDF helper and the live probe |
| tests in the TEST PLAN | written in step 5 only |

Not touched: `main.py`, lockfiles (`anthropic`, `oci`, `pypdf`, `pillow`, `python-docx` are already pinned by s01), `tests/conftest.py` (support modules are imported directly, not plugins), s02's `config_keys.py` (reads `models.*`, `extraction.fanin_timeout_seconds` as they are), s06's storage package (consumed only).

## Design

### Shared content and limiter

- `load_content_parts(parts, store)` maps s06's `ARTIFACT_PART` rows (ordered by `PART_NO`) to `ContentPart`s: `TEXT`/`TABLE` → `TextPart` (UTF-8, `errors="replace"`, prefixed `"[part {n}: {kind}]"` so readers can cite `part_no`), `DOCX` → `TextPart` (python-docx paragraphs + tables as TSV), `PDF` → `PdfPart`, `IMAGE` → `ImagePart`. Rows with `PURGED_AT` set raise `LlmError(EXTRACTION_FAILED, "artifact purged")`.
- `fit_parts(parts, *, max_text_chars=400_000, max_binary_bytes=30_000_000, max_parts=40)` is the single limiter. It never truncates silently: over budget it drops trailing parts and returns `(kept, dropped_part_nos)`; the runner records `dropped_part_nos` on the reading row's error message and in the history payload. Anthropic's request limit is 32 MB, so binary budget is 30 MB before base64 overhead check (`len(b64) <= 31 MB`).

### Reader A (`AnthropicLlmClient`)

- `__init__(client: anthropic.AsyncAnthropic, model_id: str)`; `"fable" in model_id.lower()` → `ValueError`. `provider = "anthropic"`.
- `parse`: content blocks in part order (document/image blocks first per part, then the text instruction); `output_config={"effort": request.effort}` when `effort` is set (readers always set it); `client.with_options(timeout=request.timeout_s).messages.parse(...)`. `stop_reason == "refusal"` → `LlmResult(output=None, refused=True)`; `stop_reason == "max_tokens"` → `LlmError(EXTRACTION_FAILED, "max_tokens")`; `parsed_output is None` or pydantic `ValidationError` → `LlmError(EXTRACTION_FAILED)`. Usage from `response.usage`, latency measured with `time.perf_counter`.
- `stream_text`: `client.messages.stream(...)` yielding `text_stream` deltas (s22 consumes it); refusal ends the stream with `LlmError(LLM_REFUSAL)`.
- No server-side `fallbacks` (see Assumptions).

### Reader B (`OciCohereLlmClient`)

- `__init__(transport: CohereChatTransport, *, model_id, compartment_ocid, endpoint_ocid)`; `provider = "oci-cohere"`. The real transport wraps `oci.generative_ai_inference.GenerativeAiInferenceClient(config|signer, service_endpoint=settings.oci_genai.endpoint)` (Ashburn); signer = resource principal when `OCI_RESOURCE_PRINCIPAL_VERSION` is set, else instance principal, else `~/.oci/config` for local dev. Every call goes through `asyncio.to_thread`, with the SDK `timeout=(10, request.timeout_s)`.
- Request: `ChatDetails(compartment_id, serving_mode=DedicatedServingMode(endpoint_id=endpoint_ocid), chat_request=<Cohere V2 chat request>)`. Messages: system text, then one user message with the text parts, `pdf_to_text_and_images` output for each `PdfPart` (text layer as text, page images as base64 PNG data-URL image content), images as data-URL image content, then the instruction plus `json.dumps(schema.model_json_schema())`. `response_format` = Cohere JSON-object format carrying the schema. The exact V2 class names (`CohereChatRequestV2`, `CohereUserMessageV2`, `CohereTextContentV2`, `CohereImageContentV2`/`CohereImageUrlV2`, `CohereResponseJsonFormat`) are confirmed by introspecting the pinned `oci` package during coding (`hasattr(oci.generative_ai_inference.models, ...)`), never guessed; if V2 vision classes are absent the coder uses `GenericChatRequest` + `ImageContent` and records it as an assumption.
- Output text → `schema.model_validate_json` (strip a leading/trailing ```json fence only). Failures: `ServiceError` 429/5xx and `RequestException`/timeouts → `LLM_TRANSIENT`; 4xx → `EXTRACTION_FAILED`; invalid JSON or validation error → `EXTRACTION_FAILED`; a Cohere `finish_reason` of content-filter → `refused=True`. Usage from `chat_response.usage` when present (else 0) — recorded as such, not estimated.
- `stream_text` raises `NotImplementedError("Cohere is reader-only")`.

### Extraction schema (`cashapp/domain/extraction.py`)

- `SCHEMA_VERSION = "1"`. All models `ConfigDict(extra="forbid")` (structured outputs need `additionalProperties: false`).
- `SourceLocation{part_no: int >= 1, page: int|None, bbox: BBox|None, quote: str|None (<= 300)}`, `BBox{x, y, w, h: float 0..1}`.
- `Extracted[T]{value: T|None, source: SourceLocation|None, confidence: float 0..1}` (generic `BaseModel`). `source` is nullable because a field the reader could not find has no location; the description says so.
- `RemittanceExtraction` fields exactly as AC5. `transaction_number: str` with `BeforeValidator` that refuses non-`str` input from Python (a JSON number from a reader is refused, so `2598014` can never become an int and lose `-1`/leading zeros). Money fields are `MoneyStr` (string in the JSON schema). `currency: CurrencyCode|None`; `currency_ambiguous: bool` with a model validator: `currency_raw` contains `$` and no country prefix (`US$`, `CA$`, `C$`, `A$`, `AU$`, `USD`, ...) → `currency_ambiguous=True` and `currency.value=None` (never guess; s11 resolves from the account currency). `bank_fees: list[Money]`. `payment_date: Extracted[date]`; `dates: list[DateCandidate{value: date, kind, source, confidence}]`.
- Helper methods (pure): `field_confidences() -> dict[str, float]` (field path → confidence, used by s09's "mean field confidence"), `iter_fields()`.

### `ExtractRunner`

1. `stage = Stage.EXTRACT`. Constructed with `object_store`, `llm: LlmClients`, `uow_factory`, `clock`.
2. `process(ctx)`: load `ArtifactPartRepository` rows for `ctx.item.id` (s06) and the bytes via `load_content_parts`; apply `fit_parts`.
3. Decide readers: `ctx.item.fix_hints.get("rerun_readers")` or both `("A", "B")`; effort: `fix_hints.get("effort")` for Reader A, else `config.models().reader_a.effort`; Reader B ignores effort (Cohere has none) and records `None`.
4. `clients = self.llm.with_models(ctx.config.models())` (a config change applies to the next event, no restart). Build one `LlmRequest` per reader via `build_reader_request` — same parts, same schema, same `PROMPT_VERSION`; `purpose="extract.reader_a"|"extract.reader_b"`; `timeout_s = role.timeout_s`.
5. Run selected readers as tasks; each wrapped in `asyncio.wait_for(..., role.timeout_s)` and the set in `asyncio.wait(..., timeout=config.extraction().fanin_timeout_seconds)`. Handle completions with `asyncio.as_completed` semantics: **each reading row is written in its own short UoW and committed as soon as that reader finishes** (OK/FAILED/REFUSED). Tasks still pending at the fan-in deadline are cancelled and written as `TIMEOUT`. `ATTEMPT = repo.max_attempt(item_id, reader) + 1`.
6. Outcome: the latest reading per reader (including a still-valid earlier OK reading for a reader not re-run) — if at least one is `OK` → `Advance(Stage.ADJUDICATE, note="readers: A=OK B=TIMEOUT", payload={"readings": {...ids}, "dropped_part_nos": [...], "effort_a": ...})`. Otherwise `StageError(ErrorCode.EXTRACTION_FAILED, detail={"A": status/error_code, "B": ...}, message=...)`.
7. `ROLE = consumer_role(ExtractRunner)` exposed as `RoleSpec("extract", "consumer", build)`; `build(container)` resolves `ObjectStore` and `LlmClients` through `container.resolve`.

No DB transaction is held across an LLM call: parts are read in `ctx.uow` before the fan-out, readings are written in their own UoWs, and the outcome transaction is the StageRunner's.

## Interfaces provided (pinned)

```python
# cashapp/integrations/llm/base.py
@dataclass(frozen=True, slots=True)
class TextPart:  text: str; kind: Literal["text"] = "text"
@dataclass(frozen=True, slots=True)
class ImagePart: data: bytes; media_type: Literal["image/png", "image/jpeg", "image/gif", "image/webp"]; kind: Literal["image"] = "image"
@dataclass(frozen=True, slots=True)
class PdfPart:   data: bytes; kind: Literal["pdf"] = "pdf"
ContentPart = TextPart | ImagePart | PdfPart

def parts_digest(parts: Sequence[ContentPart]) -> str
    # sha256 hex over, per part in order: kind, media_type (or ""), len, bytes (text UTF-8) — the replay key

@dataclass(frozen=True, slots=True)
class LlmRequest:
    system: str
    parts: tuple[ContentPart, ...]
    max_tokens: int
    timeout_s: float
    purpose: str                        # "<station>.<role>", e.g. "extract.reader_a", "classify.workhorse", "chat.workhorse"
    effort: str | None = None           # "low"|"medium"|"high"|"xhigh"|"max"; ignored by Cohere
    work_item_id: int | None = None
    prompt_version: str | None = None   # added now so s36 needs no edit to this file
    schema_version: str | None = None
    history: tuple[ChatTurn, ...] = ()  # prior turns for stream_text (s22); empty for parse

@dataclass(frozen=True, slots=True)
class ChatTurn: role: Literal["user", "assistant"]; text: str

@dataclass(frozen=True, slots=True)
class LlmUsage: model_id: str; input_tokens: int; output_tokens: int; latency_ms: int

@dataclass(frozen=True, slots=True)
class LlmResult(Generic[T]):
    output: T | None                    # None iff refused
    refused: bool
    stop_reason: str                    # provider stop/finish reason, verbatim
    usage: LlmUsage
    response_id: str | None = None

class LlmErrorCode(StrEnum):            # values are ErrorCode members' values (s02)
    LLM_TRANSIENT = "LLM_TRANSIENT"; LLM_REFUSAL = "LLM_REFUSAL"; EXTRACTION_FAILED = "EXTRACTION_FAILED"

class LlmError(Exception):
    code: LlmErrorCode
    provider: str
    model_id: str
    detail: str                         # no prompt/artifact/output text, ever
    usage: LlmUsage | None              # when the provider returned one
    @property
    def error_code(self) -> ErrorCode   # ErrorCode(self.code.value)

T = TypeVar("T", bound=BaseModel)

class LlmClient(Protocol):
    @property
    def provider(self) -> str: ...      # "anthropic" | "oci-cohere" | "replay"
    @property
    def model_id(self) -> str: ...
    def with_model(self, model_id: str) -> Self: ...       # cheap; shares the transport (s36's MeteredLlmClient must forward it)
    async def parse(self, request: LlmRequest, schema: type[T]) -> LlmResult[T]: ...   # raises LlmError; refusal is a result, not an error
    def stream_text(self, request: LlmRequest) -> AsyncIterator[str]: ...             # async generator; raises LlmError

@dataclass(frozen=True, slots=True)
class LlmClients:
    reader_a: LlmClient
    reader_b: LlmClient
    adjudicator: LlmClient
    workhorse: LlmClient
    def with_models(self, models: ModelsConfig) -> LlmClients   # each client .with_model(models.<role>.model_id); stations call this per event
```

```python
# cashapp/integrations/llm/factory.py
def build_llm_clients(settings: Settings, config: ConfigSnapshot | None = None) -> LlmClients
    # one AsyncAnthropic(api_key=settings.anthropic.api_key.get_secret_value(), base_url=settings.anthropic.base_url, max_retries=0)
    # shared by reader_a, adjudicator, workhorse; one OCI transport for reader_b (dedicated_endpoint_ocid, compartment_ocid, endpoint).
    # Model ids from config.models() when given, else the registry defaults (s02 MODELS_* keys). s30 calls it by import path.
```

```python
# cashapp/integrations/llm/content.py
@dataclass(frozen=True, slots=True)
class ArtifactPartRef: part_no: int; kind: str; media_type: str; object_key: str; purged: bool = False
    @classmethod
    def from_row(cls, row: Any) -> ArtifactPartRef     # duck-typed over s06's ArtifactPart ORM row
async def load_content_parts(parts: Sequence[ArtifactPartRef], store: ObjectStore) -> list[ContentPart]
@dataclass(frozen=True, slots=True)
class FittedParts: parts: tuple[ContentPart, ...]; dropped_part_nos: tuple[int, ...]
def fit_parts(parts: Sequence[ContentPart], *, max_text_chars: int = 400_000,
              max_binary_bytes: int = 30_000_000, max_parts: int = 40) -> FittedParts
# s07 (classify) uses load_content_parts + fit_parts; s09 never sends parts.

# cashapp/integrations/llm/pdf.py
@dataclass(frozen=True, slots=True)
class PdfRendering: text: str; images: tuple[ImagePart, ...]; pages: int; pages_without_content: tuple[int, ...]
def pdf_to_text_and_images(data: bytes, *, max_pages: int = 30, max_images: int = 20) -> PdfRendering
```

```python
# cashapp/integrations/llm/fake.py   (unverified against live: recordings are synthetic)
@dataclass(frozen=True, slots=True)
class ScriptedStep:
    result: LlmResult[Any] | None = None     # output may be a BaseModel or a dict (validated against the schema on parse)
    error: LlmError | None = None
    delay_s: float = 0.0                     # > request.timeout_s simulates a timeout (asyncio.sleep, cancellable)
    text_chunks: tuple[str, ...] = ()        # for stream_text
class ReplayLlmClient:                       # implements LlmClient
    def __init__(self, *, model_id: str = "replay", recordings_dir: Path | None = None,
                 script: Sequence[ScriptedStep] | Mapping[str, Sequence[ScriptedStep]] | None = None) -> None
        # script as Mapping is keyed by request.purpose; sequence is consumed in call order
        # without a scripted step, looks up recordings_dir/*.json by (purpose, parts_digest); missing → LlmError(EXTRACTION_FAILED, "no recording")
    calls: list[LlmRequest]                  # every request received, for assertions
    @staticmethod
    def refusal(model_id: str = "replay") -> ScriptedStep
    @staticmethod
    def transient(model_id: str = "replay") -> ScriptedStep
    @staticmethod
    def timeout(seconds: float = 3600.0) -> ScriptedStep
# Recording JSON (api/tests/fixtures/llm/*.json):
# {"purpose": str, "parts_sha256": str, "schema": "RemittanceExtraction@1", "result": {"output": {...}|null,
#  "refused": bool, "stop_reason": str, "usage": {...}, "response_id": str|null}, "verified_against_live": false}
```

```python
# api/tests/support/llm.py
def scripted_llm(outputs: Sequence[BaseModel | dict[str, Any] | ScriptedStep] | Mapping[str, Sequence[...]] = (),
                 *, model_id: str = "replay") -> ReplayLlmClient
def make_llm_clients(*, reader_a: LlmClient | None = None, reader_b: LlmClient | None = None,
                     adjudicator: LlmClient | None = None, workhorse: LlmClient | None = None) -> LlmClients   # defaults: empty ReplayLlmClients
def make_extraction(**overrides: Any) -> RemittanceExtraction
    # valid synthetic remittance: payer "Acme Test Payer", USD 1250.00, payment_date 2026-01-10, two INVOICE lines
    # ("INV-1001" 1000.00, "2598014-1" 250.00) all confidence 0.95; overrides replace top-level fields
    # (plain values are wrapped into Extracted(value=..., source=SourceLocation(part_no=1), confidence=0.95))
```

```python
# cashapp/domain/extraction.py
SCHEMA_VERSION: Final = "1"
class ReaderSlot(StrEnum): A = "A"; B = "B"
class ReadingStatus(StrEnum): OK = "OK"; FAILED = "FAILED"; TIMEOUT = "TIMEOUT"; REFUSED = "REFUSED"
class DateKind(StrEnum): PAYMENT = "payment"; ISSUE = "issue"; ORDER = "order"; DEPOSIT = "deposit"; OTHER = "other"
class LineKind(StrEnum): INVOICE CREDIT_MEMO UNKNOWN BANK_FEE TARIFF DISCOUNT   # value == name
class BBox(BaseModel): x: float; y: float; w: float; h: float                     # 0..1
class SourceLocation(BaseModel): part_no: int; page: int | None = None; bbox: BBox | None = None; quote: str | None = None
class Extracted(BaseModel, Generic[V]): value: V | None = None; source: SourceLocation | None = None; confidence: float  # 0..1
class DateCandidate(BaseModel): value: date; kind: DateKind; source: SourceLocation | None = None; confidence: float
class ExtractedLine(BaseModel):
    line_no: int; kind: LineKind; transaction_number: str            # strict string; "" allowed only for BANK_FEE/TARIFF/DISCOUNT
    amount_paid: MoneyStr | None = None; gross_amount: MoneyStr | None = None
    discount_claimed: MoneyStr | None = None; deduction: MoneyStr | None = None
    po_number: str | None = None; sales_order: str | None = None; ers_reference: str | None = None
    source: SourceLocation | None = None; confidence: float
class RemittanceExtraction(BaseModel):
    payer_name: Extracted[str]; payer_bank_account: Extracted[str]; remittance_reference: Extracted[str]
    payment_amount: Extracted[MoneyStr]; currency_raw: Extracted[str]; currency: Extracted[CurrencyCode]
    currency_ambiguous: bool; dates: list[DateCandidate]; payment_date: Extracted[date]
    lines: list[ExtractedLine]; po_refs: list[str]; sales_order_refs: list[str]; ers_refs: list[str]
    bank_fees: list[Money]; notes: str | None = None
    def field_confidences(self) -> dict[str, float]     # "payer_name" ..., "lines[0]" ...; s09 mean-confidence input
```

```python
# cashapp/data/models/extraction_reading.py  (table extraction_reading → EXTRACTION_READING)
class ExtractionReading(Base):
    id: int (identity PK); work_item_id: int (FK work_item.id, FK_EXTRACTION_READING_WI); reader: ReaderSlot
    model_id: str (String(100)); prompt_version: str (String(20)); schema_version: str (String(20))
    status: ReadingStatus; output: dict | None (JsonDoc); error_code: ErrorCode | None
    error_message: str | None (String(2000), no content text); input_tokens: int | None; output_tokens: int | None
    latency_ms: int | None; attempt: int; effort: str | None (String(10)); created_at: datetime (UtcDateTime); purged_at: datetime | None

# cashapp/data/repositories/readings.py
class ExtractionReadingRepository(BaseRepository[ExtractionReading]):
    async def latest_for(self, item_id: int) -> dict[ReaderSlot, ExtractionReading]   # max ATTEMPT per reader (ties → max id); s09
    async def for_item(self, item_id: int) -> list[ExtractionReading]                 # ordered attempt, reader, id; s19
    async def max_attempt(self, item_id: int, reader: ReaderSlot) -> int              # 0 when none
    async def purge_outputs(self, item_ids: Sequence[int], *, at: datetime) -> int    # s45: OUTPUT=NULL, PURGED_AT=at
```

```python
# cashapp/stations/extract/prompts.py
PROMPT_VERSION: Final = "1"
EXTRACT_MAX_TOKENS: Final = 16000
READER_SYSTEM_PROMPT: Final[str]
DESC_*: Final[str]                       # field-description constants imported by domain/extraction.py
def build_reader_request(parts: Sequence[ContentPart], *, role: ModelRole, effort: str | None, slot: ReaderSlot,
                         work_item_id: int) -> LlmRequest   # identical system/parts for A and B; only purpose/effort/timeout differ

# cashapp/stations/extract/runner.py
class ExtractRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.EXTRACT
    def __init__(self, *, object_store: ObjectStore, llm: LlmClients, uow_factory: UowFactory, clock: Clock, **runner_kwargs: Any) -> None
    async def process(self, ctx: StageContext) -> StageOutcome
def build(container: Container) -> Runnable
ROLE: RoleSpec   # RoleSpec("extract", "consumer", build)
```

Dependency note: `cashapp/domain/extraction.py` importing description constants from `cashapp/stations/extract/prompts.py` would invert the layers, so the constants live in `cashapp/domain/extraction_text.py` (new, owned here) and `prompts.py` imports them from there.

## Migrations

- One revision `api/alembic/versions/<rev>_s08_extraction_reading.py`, hand-written. Expected parent: the current head when coded (s06's `ARTIFACT_PART` revision if merged first, otherwise the wave-1 head); the merger re-points `down_revision` and checks `alembic heads` returns one head.
- Creates `EXTRACTION_READING`: `ID` identity PK; `WORK_ITEM_ID NUMBER NOT NULL` FK → `WORK_ITEM.ID` (`FK_EXTRACTION_READING_WI`); `READER VARCHAR2(40) NOT NULL`; `MODEL_ID VARCHAR2(100) NOT NULL`; `PROMPT_VERSION VARCHAR2(20) NOT NULL`; `SCHEMA_VERSION VARCHAR2(20) NOT NULL`; `STATUS VARCHAR2(40) NOT NULL`; `OUTPUT JSON NULL`; `ERROR_CODE VARCHAR2(40) NULL`; `ERROR_MESSAGE VARCHAR2(2000) NULL`; `INPUT_TOKENS NUMBER(10)`, `OUTPUT_TOKENS NUMBER(10)`, `LATENCY_MS NUMBER(10)` NULL; `ATTEMPT NUMBER(5) NOT NULL`; `EFFORT VARCHAR2(10) NULL` (additive, see Assumptions); `CREATED_AT TIMESTAMP WITH TIME ZONE NOT NULL`; `PURGED_AT TIMESTAMP WITH TIME ZONE NULL`. Index `IX_EXTRACTION_READING_ITEM` (`WORK_ITEM_ID`, `READER`, `ATTEMPT`). No CHECK constraints (s02 enum rule). JSON via s02's `JsonDoc`.
- Downgrade drops the index and table. DEV ATP only.

## TEST PLAN (written and run in step 5 only)

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `tests/integrations/llm/test_base.py::test_llm_request_result_shapes` | Dataclasses frozen; `LlmResult` with `refused=True` has `output=None`; `LlmError.error_code` maps to the s02 `ErrorCode` for all three codes. |
| 1 | `…::test_parts_digest_stable_and_order_sensitive` | Same parts → same digest across calls; reordering or changing one byte changes it. |
| 1 | `…::test_replay_and_real_clients_satisfy_protocol` | `isinstance`-free structural check: pyright-checked assignment of `AnthropicLlmClient`, `OciCohereLlmClient`, `ReplayLlmClient` to `LlmClient` variables (static) plus a runtime attribute check. |
| 1 | `tests/integrations/llm/test_factory.py::test_build_llm_clients_uses_config_models` | With a `make_config_snapshot` overriding `models.workhorse`, the bundle's `workhorse.model_id` matches; reader_b is the Cohere client bound to `dedicated_endpoint_ocid`; one shared `AsyncAnthropic` for three roles. |
| 1 | `…::test_with_models_rebinds_without_new_transport` | `with_models` changes model ids and keeps the same underlying transport objects. |
| 2 | `tests/integrations/llm/test_anthropic_client.py::test_parse_sends_structured_output_and_effort` | Fake `AsyncAnthropic` captures kwargs: `output_format is RemittanceExtraction`, `output_config == {"effort": "high"}`, no `tool_choice`, no `tools`, no `thinking`, no `temperature`; PDF → `document` base64 block, image → `image` block, both before the text block. |
| 2 | `…::test_refusal_checked_before_content` | Response with `stop_reason="refusal"` and a `parsed_output` property that raises if read → `LlmResult(refused=True, output=None)`, property never accessed. |
| 2 | `…::test_transient_errors_map_to_llm_transient` | `RateLimitError`, `InternalServerError` (500/529 overloaded), `APITimeoutError`, `APIConnectionError` → `LlmError(LLM_TRANSIENT)`; `BadRequestError` → `EXTRACTION_FAILED`; `max_tokens` stop → `EXTRACTION_FAILED`. |
| 2 | `…::test_constructor_refuses_fable` | `"claude-fable-5-1"`, `"CLAUDE-FABLE-5"` → `ValueError`; `with_model("claude-fable-5")` also refuses. |
| 2 | `…::test_stream_text_uses_messages_stream` | Fake stream yields deltas in order; refusal mid-stream raises `LlmError(LLM_REFUSAL)`. |
| 3 | `tests/integrations/llm/test_oci_cohere_client.py::test_chat_uses_dedicated_serving_mode` | Fake transport captures `ChatDetails`: `serving_mode` is `DedicatedServingMode(endpoint_id=<settings value>)`, compartment set, call ran via `asyncio.to_thread` (thread id differs from loop thread). |
| 3 | `…::test_pdf_sent_as_text_and_png_images` | A synthetic PDF part produces text content + PNG data-URL image contents; JSON schema text and JSON response format present. |
| 3 | `…::test_output_validated_with_pydantic` | Valid JSON → typed `RemittanceExtraction`; invalid JSON / schema mismatch / numeric `transaction_number` → `LlmError(EXTRACTION_FAILED)`. |
| 3 | `…::test_failures_mapped` | `ServiceError` 429/503 and timeouts → `LLM_TRANSIENT`; 400 → `EXTRACTION_FAILED`; content-filter finish → `refused=True`. |
| 3 | `…::test_stream_text_not_implemented` | `NotImplementedError`. |
| 3 | `tests/integrations/llm/test_pdf.py::test_pdf_to_text_and_images` | Fixture PDF: text layer extracted, embedded image re-encoded as PNG, caps honoured, pages without content listed. |
| 4 | `tests/integrations/llm/test_fake.py::test_replay_from_recordings_by_purpose_and_digest` | Recording file returned for matching `(purpose, parts_sha256)`; mismatch → `LlmError(EXTRACTION_FAILED)`. |
| 4 | `…::test_scripted_sequence_refusal_timeout_transient` | Steps consumed in order; `refusal()` → refused result; `transient()` raises `LLM_TRANSIENT`; `timeout()` is cancelled by `asyncio.wait_for`; `calls` records requests. |
| 5 | `tests/domain/test_extraction_schema.py::test_invoice_numbers_round_trip_as_strings` | `"2598014"` and `"2598014-1"` survive `model_dump_json` → `model_validate_json` as `str`; a JSON number for `transaction_number` is rejected. |
| 5 | `…::test_line_with_no_amounts_is_valid` | Line with all amounts `None` validates and round-trips. |
| 5 | `…::test_money_fields_are_strings_in_json_schema` | `model_json_schema()` money fields are `type: string` with the s02 pattern; no `float` anywhere for money. |
| 5 | `…::test_dollar_sign_marks_currency_ambiguous` | `currency_raw="$"` → `currency_ambiguous=True`, `currency.value is None`; `"US$"` → not ambiguous. |
| 5 | `…::test_multiple_dates_kept_and_one_chosen` | `dates` keeps all candidates with kinds; `payment_date` is independent. |
| 5 | `…::test_schema_accepted_by_structured_outputs_shape` | Every object in the JSON schema has `additionalProperties: false`; `schema_version == "1"`. |
| 5 | `…::test_make_extraction_defaults_valid` | `make_extraction()` validates; overrides wrap plain values. |
| 6 | `tests/stations/extract/test_prompts.py::test_both_readers_get_same_parts_and_schema` | `build_reader_request` for A and B: identical `system` and `parts`, same `prompt_version`/`schema_version`; only purpose/effort/timeout differ. |
| 6 | `…::test_field_descriptions_come_from_shared_constants` | Every `Field(description=...)` in `RemittanceExtraction` equals a constant in `extraction_text.py`; `PROMPT_VERSION` is a non-empty string. |
| 7 | `tests/integration/test_extraction_reading_migration_atp.py::test_upgrade_downgrade_atp` (`-m atp`) | Table and columns exactly as listed, `OUTPUT` native JSON, identity PK, FK; downgrade drops; one Alembic head. |
| 7 | `tests/data/test_readings_repository.py::test_latest_for_and_max_attempt` (sqlite) | `latest_for` picks max attempt per reader; `max_attempt` 0 when empty; `purge_outputs` nulls OUTPUT and sets PURGED_AT. |
| 8 | `tests/stations/extract/test_extract_runner.py::test_both_ok_persists_two_rows_and_advances` | Two OK rows (reader, model, prompt/schema version, tokens, attempt 1); outcome `Advance(ADJUDICATE)`. |
| 8 | `…::test_readers_run_concurrently` | Two scripted readers with `delay_s=0.2` finish in < 0.35 s total. |
| 8 | `…::test_row_written_as_each_reader_completes` | Reader A fast, B slow: A's row is committed and visible from a separate UoW before B finishes. |
| 8 | `…::test_one_timeout_still_advances` | B exceeds `fanin_timeout_seconds` (overridden to 1) → B row `TIMEOUT`, A `OK` → `Advance(ADJUDICATE)`. |
| 8 | `…::test_refused_and_failed_rows_recorded` | A refused → `REFUSED` row with `ERROR_CODE=LLM_REFUSAL`; B transient → `FAILED` row with `LLM_TRANSIENT`; both failed → `StageError(EXTRACTION_FAILED)` with per-reader detail. |
| 8 | `…::test_rerun_only_failed_reader_with_higher_effort` | `fix_hints={"rerun_readers": ["B"], "effort": "max"}` on an item with A OK (attempt 1), B FAILED (attempt 1): only B called, new row attempt 2; A not re-called; advances using A's earlier OK. Separately `rerun_readers=["A"]` sends `effort="max"` to A. |
| 8 | `…::test_model_change_applies_next_event` | Changing `models.reader_a` in the config snapshot changes `MODEL_ID` on the next event without rebuilding the runner. |
| 8 | `…::test_parts_loaded_from_object_store_and_limited` | Parts read via `LocalFolderObjectStore` in `PART_NO` order; over-budget parts dropped and listed in the payload; purged part → `StageError(EXTRACTION_FAILED)`. |
| 8 | `…::test_no_content_in_logs_or_spans` | Sentinel strings in the artifact and output never appear in `caplog` or exported span attributes; span `llm.reader_a` carries token attributes. |
| 9 | `tests/stations/extract/test_role.py::test_role_spec` | `ROLE.name == "extract"`, `kind == "consumer"`, `build(container)` returns a `Runnable` using `container.resolve(LlmClients)` and `container.resolve(ObjectStore)`. |
| 10 | `tests/live/test_llm_live.py::test_opus_reader_live` (`-m live`) | Skipped without `CASHAPP_ANTHROPIC__API_KEY`; one Opus `parse` on the synthetic PDF returns a `RemittanceExtraction` with the known payment amount. |
| 10 | `…::test_cohere_dedicated_endpoint_live` (`-m live`) | Skipped without OCI credentials/endpoint; one Cohere call on the synthetic PNG validates; on pass, prints the marker used to flip `verified_against_live` in the fixtures README (the coder records the result; until then the Cohere shape stays "unverified against live"). |

## Assumptions / deviations

- **Readings are committed in their own short UoWs**, not in `ctx.uow`, so a crash after one reader finishes keeps that reading ("persists each reading row separately as it completes"). The outcome transaction stays the StageRunner's. The runner therefore takes `uow_factory` (from the container).
- **`LlmClients.with_models(models)` and `LlmClient.with_model(model_id)`** are added to the AC1 surface so a model-id change in config applies per event (s07 AC5) without rebuilding SDK clients. s36's `MeteredLlmClient` must forward `with_model`.
- **`LlmRequest.prompt_version`/`schema_version`/`history`** are added now (defaults keep the AC1 call shape) so s36 and s22 don't edit `base.py`. `parts` is a tuple (frozen dataclass) rather than a list.
- **`build_llm_clients(settings, config=None)`**: `config` is a `ConfigSnapshot` (s28); `None` uses registry defaults, which s30 may pass at process start. Stations rebind per event with `with_models`.
- **No server-side refusal `fallbacks`** on Opus calls, although the claude-api skill defaults to it: the fallback could route to a model outside the fixed role table or one not eligible for zero retention (CLAUDE.md: roles are a decision; ZDR mandatory). A refusal is recorded as `REFUSED` and handled by s18.
- **PDF → images for Cohere without a renderer**: no PDF rasteriser is pinned and lockfiles are frozen, so `pdf.py` uses pypdf's text layer plus the page's embedded images (scanned PDFs are one image per page). Vector-only pages contribute text only; listed in `pages_without_content`. If quality needs true rendering, adding `pypdfium2` is a lockfile change for a later story.
- **`EFFORT` column** added to `EXTRACTION_READING` (not in AC7) so the "re-run at higher effort" auto-fix is auditable. Additive and nullable.
- **`Extracted.source` is nullable** (a missing field has no location). Confidence is still required.
- **`TIMEOUT` vs `FAILED`**: a reader timeout is `TIMEOUT` with `ERROR_CODE=LLM_TRANSIENT`; a provider transient error is `FAILED` with `LLM_TRANSIENT`.
- **SDK retries disabled** (`max_retries=0`); every retry goes through s18 so each attempt is a recorded reading row.
- **Description constants** live in `cashapp/domain/extraction_text.py` (domain may not import stations).
- **Live probe skip conditions** use env presence, never call with placeholder keys (a 401 would mislead).

## Risks

- **Cohere V2 vision request shape is unverified** (classes, JSON response format with schema, image limits per request, finish reasons on the dedicated endpoint). Mitigation: introspect the pinned `oci` package while coding; the `-m live` probe; the fake is labelled unverified.
- **`asyncio.to_thread` can't be cancelled**: on fan-in timeout the Cohere thread keeps running until the SDK read timeout (`timeout_s`) fires. Bounded by setting the SDK timeout equal to the role timeout; a thread may still occupy the default executor briefly.
- **Opus at `high` effort on a long PDF may exceed the 120 s default `timeout_s`/180 s fan-in**. Both are config; the live probe reports latency so defaults can be tuned. Non-streaming `parse` with `max_tokens=16000` stays under SDK HTTP limits.
- **Structured-output schema complexity**: the generic `Extracted[T]` creates many `$defs`; Anthropic structured outputs may reject unsupported constraints (`ge/le` on floats, `pattern`). The SDK's `parse` strips unsupported constraints and validates client-side; the unit test asserts `additionalProperties: false`; the live probe confirms acceptance.
- **Cost**: two readers per artifact plus Opus `high` thinking. s36 meters it; the dedicated Cohere cluster bills hourly regardless.
- **Stale `FIX_HINTS`**: the runner reads but does not clear `fix_hints`; s18 must clear or overwrite them, otherwise a later human requeue could re-run only one reader.
- **Parallel-wave contracts**: `StageRunner` constructor kwargs (s03), `ArtifactPartRepository` name (s06) and `span` (s29) are coded against their story ACs; the merger reconciles names if their plans differ.
