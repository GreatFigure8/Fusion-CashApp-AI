# Plan: s27-settings-secrets-wiring

Issue #27. Wave 1, serialized spine step 2 (after s01, before s02). Deploy-time settings only;
business-tunable values belong to s28. Follows research.md (a3: pydantic-settings; `SecretSource`
with exactly two implementations) and `python-web-app:wiring-application-config`.

## Standards followed

- `python-web-app:wiring-application-config`: one typed model, strict at the load boundary
  (consumers index attributes, never `.get(default)`), closed surface (`extra="forbid"` on every
  group, so a misspelled env var under a known group fails instead of being kept silently),
  a coverage test between the model and the shipped `.env.example`, no `or`-defaults for falsy-valid
  values, and loaders that take an explicit path (`env_file`) so tests never read the repo's `.env`.
- `python-web-app:building-python-web-apps`: settings are built once and injected. Services get
  `Settings` (or one group) as a plain argument; `cashapp/settings.py` imports no FastAPI.
- CLAUDE.md: all hosting in Ashburn (`object_storage.region` is `Literal["us-ashburn-1"]`), secrets
  from OCI Vault, nothing secret in `NEXT_PUBLIC_*`, PII and secrets never logged.
- `nextjs-fullstack-standards` + BMN `references/nextjs.md`: Zod at the boundary, `server-only` for
  server modules, strict TS with `noUncheckedIndexedAccess`.
- pyright strict on `src/`; ruff.

## Files to touch

All are owned by this story. s01 creates `main.py` and `alembic/env.py`; this story makes the one
planned edit to each (s01 AC4 says "wired in s27").

| Path | Action |
|---|---|
| `api/src/cashapp/settings.py` | new: `Settings`, groups, `load_settings`, `aload_settings`, `get_settings`, `SettingsError`, `env_var_names` |
| `api/src/cashapp/secrets.py` | new: `SecretSource`, `VaultSecretSource`, `EnvSecretSource`, `SecretResolutionError`, `resolve_secret_refs` |
| `api/src/cashapp/main.py` | edit: `create_app()` calls `get_settings()` first, so a bad config fails before the app is built (no other change) |
| `api/alembic/env.py` | edit: build the URL and `connect_args` from `get_settings().atp` |
| `api/.env.example` | new: every setting, placeholders only |
| `api/tests/support/__init__.py` | new (empty package; s04 and others add modules) |
| `api/tests/support/settings.py` | new: `make_settings`, `isolated_env` fixture |
| `api/tests/unit/test_settings.py` | new (tests, written at step 5) |
| `api/tests/unit/test_secrets.py` | new (tests, written at step 5) |
| `api/tests/unit/test_env_example.py` | new (tests, written at step 5) |
| `web/lib/env.ts` | new: `serverEnv` (server-only), re-exports `publicEnv`, `parseServerEnv`, `assertServerEnv`, `EnvError` |
| `web/lib/env.public.ts` | new: `publicEnv` (safe in client components) |
| `web/instrumentation.ts` | new: `register()` calls `assertServerEnv()` in the Node.js runtime, so boot fails fast |
| `web/.env.example` | new: every web variable, placeholders only |
| `web/tests/unit/env.test.ts` | new (tests, written at step 5) |

No lockfile edits: `pydantic-settings`, `oci`, `zod` and `server-only` come from s01. **If
`server-only` is not in s01's `package.json`, record it and add it in s01's lockfile change at
merge; s27 does not edit the lockfile on its own.**

## Design

### Environment variable naming (pinned)

- Prefix `CASHAPP_`, nested delimiter `__`, case-insensitive. Examples: `CASHAPP_ENV`,
  `CASHAPP_ATP__DSN`, `CASHAPP_FUSION__WRITE_ENABLED`, `CASHAPP_FUSION__PODS__DEV__BASE_URL`.
  The prefix keeps the app away from the OCI SDK's own `OCI_*` variables.
- Locally, `api/.env` (gitignored) is read when present. `load_settings(env_file=None)` turns that off.

### Vault references

- Any string or `SecretStr` leaf whose value is `vault:<secret-ocid>` is a reference. The loader
  collects every reference, deduplicates them, resolves them concurrently with `asyncio.gather` once
  at startup, and validates the model again with the resolved values.
- Source selection: `env == "local"` → `EnvSecretSource()`; anything else →
  `VaultSecretSource.from_environment()`. A caller (tests) can pass `secret_source=` explicitly.
- Resolution failure raises `SettingsError` naming the setting path and the OCID (an OCID is not
  secret), never the value.

### Fail fast with one error

`load_settings` catches pydantic's `ValidationError` and raises `SettingsError` **`from None`**.
The original error is never chained, because pydantic's message carries `input_value` and a chained
traceback would print secrets. The message lists every problem as env var names:

```
Invalid settings: missing CASHAPP_ATP__DSN, CASHAPP_ANTHROPIC__API_KEY; invalid CASHAPP_WORKER__HEALTH_PORT (int_parsing)
```

`SettingsError.missing: tuple[str, ...]` and `SettingsError.invalid: tuple[str, ...]` (names plus
the pydantic error *type* only, no input).

### Sync and async loading

- `aload_settings(...)` is the async core.
- `load_settings(...)` is sync. With no running loop it calls `asyncio.run`. Inside a running loop
  (uvicorn imports the app inside its loop; Alembic's async `env.py` runs inside `asyncio.run`), it
  runs `asyncio.run` in a one-shot worker thread and joins it. This happens once per process, at
  startup only.
- `get_settings()` is `functools.cache`d around `load_settings()`. Tests call
  `get_settings.cache_clear()`.

## Interfaces provided (pinned)

### `api/src/cashapp/settings.py`

```python
Env = Literal["local", "dev", "test", "prod"]

class AtpSettings(BaseModel):            # all groups: model_config = ConfigDict(extra="forbid", frozen=True)
    dsn: str                             # TNS alias or full connect descriptor / Easy Connect string
    user: str
    password: SecretStr
    wallet_dir: str | None = None        # thin mode: config_dir + wallet_location
    wallet_password: SecretStr | None = None   # deviation: thin mode needs it for an encrypted ewallet.pem
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout_seconds: int = 30
    def url(self) -> sqlalchemy.engine.URL          # "oracle+oracledb://" with username/password, no host
    def connect_args(self) -> dict[str, object]     # {"dsn", and when wallet_dir: "config_dir", "wallet_location", "wallet_password"}
    def engine_kwargs(self) -> dict[str, object]    # {"pool_size", "max_overflow", "pool_timeout", "pool_pre_ping": True, "connect_args": connect_args()}

class StreamingSettings(BaseModel):
    bootstrap_servers: str               # "cell-1.streaming.us-ashburn-1.oci.oraclecloud.com:9092"
    sasl_username: str                   # "<tenancy>/<user>/<stream-pool-ocid>"
    sasl_password: SecretStr             # auth token
    topic_prefix: str = "cashapp"
    consumer_group: str                  # never renamed or reset (CLAUDE.md)
    env: str | None = None               # topic env label; filled from Settings.env when unset
    @property
    def topic_env(self) -> str           # always a str after load; s03 builds topics with this

class ObjectStorageSettings(BaseModel):
    namespace: str
    bucket: str
    region: Literal["us-ashburn-1"] = "us-ashburn-1"

class AnthropicSettings(BaseModel):
    api_key: SecretStr
    base_url: str | None = None

class OciGenAiSettings(BaseModel):
    endpoint: str = "https://inference.generativeai.us-ashburn-1.oci.oraclecloud.com"
    compartment_ocid: str
    dedicated_endpoint_ocid: str

class IdentitySettings(BaseModel):
    issuer: str
    jwks_url: str
    audience: str
    groups_claim: str = "groups"         # unverified against live (s04)
    bootstrap_admin_group: str = "CashApp-Admins"

class FusionTestDataSettings(BaseModel):  # consumed by s23; optional per pod
    business_unit: str
    transaction_type: str
    receipt_method: str
    bank_account: str

class FusionPodSettings(BaseModel):
    base_url: str                         # https://<pod>.fa.<dc>.oraclecloud.com, no trailing slash (validator strips it)
    username: str
    password: SecretStr
    is_production: bool = False
    testdata: FusionTestDataSettings | None = None

class FusionSettings(BaseModel):
    pods: dict[str, FusionPodSettings]    # keys lower-cased; at least one
    default_pod: str                      # validator: must be a key of pods
    write_enabled: bool = False
    relationships_report_path: str        # BIP catalog path of the pay-on-behalf report (s32)

class ObservabilitySettings(BaseModel):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    otlp_endpoint: str | None = None
    oci_monitoring_namespace: str = "cashapp"

class WorkerSettings(BaseModel):
    health_port: int = 8081
    shutdown_grace_seconds: int = 30

class IntakeSettings(BaseModel):
    drop_folder: str

class SmtpSettings(BaseModel):
    host: str
    port: int = 587
    username: str
    password: SecretStr
    from_address: str

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CASHAPP_", env_nested_delimiter="__",
                                      case_sensitive=False, extra="forbid", frozen=True)
    env: Env
    atp: AtpSettings
    streaming: StreamingSettings
    object_storage: ObjectStorageSettings
    anthropic: AnthropicSettings
    oci_genai: OciGenAiSettings
    identity: IdentitySettings
    fusion: FusionSettings
    observability: ObservabilitySettings = ObservabilitySettings()
    worker: WorkerSettings = WorkerSettings()
    intake: IntakeSettings
    smtp: SmtpSettings | None = None
    # model_validator(after): streaming.env defaults to env

class SettingsError(Exception):
    missing: tuple[str, ...]
    invalid: tuple[str, ...]

def load_settings(*, secret_source: SecretSource | None = None,
                  env_file: str | Path | None = ".env") -> Settings
async def aload_settings(*, secret_source: SecretSource | None = None,
                         env_file: str | Path | None = ".env") -> Settings
def get_settings() -> Settings            # functools.cache; used by main.py, alembic/env.py, s30 worker host
def env_var_names() -> list[str]          # every leaf as an env var name; dict keys rendered as "<POD>"
```

Consumers: s02 (`get_settings().atp.url()/engine_kwargs()`), s03 (`streaming`, `topic_env`),
s04 (`identity`), s05 (`fusion`, `env`), s06 (`object_storage`, `intake`), s08 (`anthropic`,
`oci_genai`), s23 (`fusion.pods[...].testdata`), s29 (`observability`), s30 (`worker`, `get_settings`),
s42 (`smtp`), s25/s44 (env var names and `vault:` values).

### `api/src/cashapp/secrets.py`

```python
VAULT_PREFIX = "vault:"

class SecretSource(Protocol):
    async def resolve(self, ref: str) -> str: ...     # ref is the secret OCID, prefix already stripped

class SecretResolutionError(Exception):
    ref: str                                         # the OCID; never a value

class VaultSecretSource:
    def __init__(self, client: SecretsClientLike) -> None
    @classmethod
    def from_environment(cls) -> "VaultSecretSource"  # resource-principal signer when OCI_RESOURCE_PRINCIPAL_VERSION is set,
                                                      # else instance-principal signer; region us-ashburn-1
    async def resolve(self, ref: str) -> str          # asyncio.to_thread(client.get_secret_bundle, secret_id=ref, stage="CURRENT");
                                                      # base64-decodes data.secret_bundle_content.content as UTF-8

class EnvSecretSource:                               # the env/fake implementation
    def __init__(self, values: Mapping[str, str] | None = None) -> None   # default os.environ
    async def resolve(self, ref: str) -> str          # values[ref]; KeyError -> SecretResolutionError(ref)

class SecretsClientLike(Protocol):
    def get_secret_bundle(self, secret_id: str, *, stage: str = ...) -> Any: ...

def is_secret_ref(value: str) -> bool
async def resolve_secret_refs(data: dict[str, Any], source: SecretSource) -> dict[str, Any]
    # walks nested dicts; returns a new dict, input untouched (deep copy, not {**data})
```

### `api/tests/support/settings.py`

```python
def make_settings(**overrides: Any) -> Settings
    # env="local", fake placeholder values for every required field, one pod "dev";
    # overrides deep-merged per group (dict) or replaced (model instance);
    # built with Settings.model_validate(...) so no env var or .env file is read
@pytest.fixture
def isolated_env(monkeypatch) -> None   # deletes every CASHAPP_* var and chdirs to tmp_path (no stray .env)
```

### `web/lib/env.ts` (starts with `import "server-only"`)

```ts
export const serverEnvSchema = z.object({
  OIDC_ISSUER: z.string().url(),
  OIDC_CLIENT_ID: z.string().min(1),
  OIDC_CLIENT_SECRET: z.string().min(1),
  SESSION_SECRET: z.string().min(32),
  API_BASE_URL: z.string().url(),
  APP_BASE_URL: z.string().url(),
});
export type ServerEnv = z.infer<typeof serverEnvSchema>;
export class EnvError extends Error { readonly missing: string[]; readonly invalid: string[] }  // names only, never values
export function parseServerEnv(source: Record<string, string | undefined>): ServerEnv;  // throws EnvError
export function assertServerEnv(): void;               // validates process.env once (memoized)
export const serverEnv: Readonly<ServerEnv>;           // lazily validated on first property access, then frozen
export { publicEnv } from "./env.public";
```

### `web/lib/env.public.ts` (no `server-only`; safe in client components)

```ts
export const publicEnvSchema = z.object({ NEXT_PUBLIC_ENV_LABEL: z.string().default("LOCAL") });
export type PublicEnv = z.infer<typeof publicEnvSchema>;
export const publicEnv: Readonly<PublicEnv>;   // reads the literal process.env.NEXT_PUBLIC_ENV_LABEL so Next inlines it
```

Client components (s19 env badge) import `@/lib/env.public`. Server code imports `@/lib/env`.

`web/instrumentation.ts`: `export async function register()` → when
`process.env.NEXT_RUNTIME === "nodejs"`, dynamic-import `./lib/env` and call `assertServerEnv()`.
`next build` does not validate (env is absent at build time); `next start` / `next dev` boot does.

## Migrations

None.

## TEST PLAN (written and run only at step 5)

| AC | Test (file::name) |
|---|---|
| 1 | `api/tests/unit/test_settings.py::test_settings_groups_and_fields_match_contract`: field names and types of every group, `env` literal, defaults (`groups_claim`, `bootstrap_admin_group`, `write_enabled=False`, `shutdown_grace_seconds=30`, `smtp is None`) |
| 1 | `test_settings.py::test_nested_env_vars_populate_fusion_pods`: `CASHAPP_FUSION__PODS__DEV__*` env produces `pods["dev"]`; `default_pod` not in pods is rejected |
| 1 | `test_settings.py::test_object_storage_region_must_be_ashburn` |
| 1 | `test_settings.py::test_streaming_topic_env_defaults_to_env` |
| 1 | `test_settings.py::test_atp_url_and_connect_args`: `oracle+oracledb` drivername, wallet keys present only when `wallet_dir` is set |
| 2 | `test_settings.py::test_missing_required_values_listed_in_one_error`: blank env → one `SettingsError` naming every missing var, `__cause__ is None` and `__suppress_context__` is set |
| 2 | `test_settings.py::test_settings_error_never_contains_values`: an invalid value with a secret-looking password is absent from `str(err)` and the formatted traceback |
| 3 | `api/tests/unit/test_secrets.py::test_vault_source_decodes_base64_bundle`: fake `SecretsClientLike`, runs off-loop (`asyncio.to_thread`) |
| 3 | `test_secrets.py::test_env_source_resolves_and_raises_on_unknown_ref` |
| 3 | `test_secrets.py::test_load_settings_resolves_vault_refs_once`: two fields with the same `vault:` ref → resolved once; values land in `SecretStr` |
| 3 | `test_secrets.py::test_source_selection_local_env_vs_vault`: `env="local"` uses `EnvSecretSource`; `env="dev"` calls `VaultSecretSource.from_environment` (patched) |
| 3 | `test_secrets.py::test_load_settings_works_inside_running_loop` |
| 4 | `test_settings.py::test_get_settings_is_cached` (same object twice; `cache_clear` reloads) |
| 4 | `test_settings.py::test_alembic_env_reads_atp_from_get_settings`: static check that `alembic/env.py` imports `get_settings` and uses `.atp` with no other URL source; `main.py` calls `get_settings` |
| 5 | `web/tests/unit/env.test.ts` › `parseServerEnv lists every missing name`, `rejects SESSION_SECRET shorter than 32`, `error message holds names not values`, `publicEnv exposes only NEXT_PUBLIC_ENV_LABEL`, `env.ts imports server-only` (static), `no NEXT_PUBLIC_ variable holds a secret name` (static scan of `web/.env.example`) |
| 6 | `api/tests/unit/test_env_example.py::test_every_setting_in_env_example`: `env_var_names()` (with `<POD>`→`DEV`) ⊆ names in `api/.env.example`, and the reverse (no stale names) |
| 6 | `test_env_example.py::test_env_example_has_placeholders_only`: every value is empty, `<...>`, `vault:ocid1.vaultsecret.oc1.iad.<...>`, or a documented non-secret default |
| 6 | `web/tests/unit/env.test.ts` › `.env.example lists every schema key` |
| 7 | `test_settings.py::test_repr_and_logs_hide_secrets`: `repr`, `str`, `model_dump_json()` and a `caplog` record of `settings` contain none of the fake secret values (atp, streaming, anthropic, pod, smtp passwords) |

## Risks

- **Event-loop clash at startup.** Uvicorn and Alembic call into loading from inside a running loop.
  The thread fallback in `load_settings` handles it; the test for that path is in the plan.
- **pydantic-settings and `dict[str, Model]` from env.** Nested delimiter parsing of
  `PODS__DEV__BASE_URL` is supported, but the coder must check case handling of the dict key
  (keys are lower-cased by a validator).
- **`model_validate` on `BaseSettings` skipping env sources** is what `make_settings` relies on. If a
  pydantic-settings version reads sources there, fall back to a test subclass whose
  `settings_customise_sources` returns only `init_settings`, and record it.
- **`server-only` in middleware (s04).** Middleware importing `@/lib/env` may fail at build. s04 can
  read `SESSION_SECRET` through `parseServerEnv(process.env)` in a module without `server-only` if so.
- **`web/instrumentation.ts`** is created here. Any later story needing web instrumentation (none
  planned) appends to it rather than creating a second one.
- Vault auth (resource vs instance principal) depends on s25's compute choice. Both are supported,
  and it is recorded as "unverified against live".

## Assumptions / deviations

- Env var prefix `CASHAPP_` with `__` nesting (story didn't name a scheme). research.md's
  `FUSION_WRITE_ENABLED` becomes `CASHAPP_FUSION__WRITE_ENABLED`.
- Added `atp.wallet_password` and `atp.pool_timeout_seconds`, `fusion.pods[*].testdata` (s23's
  "settings of the dev pod"), and `streaming.topic_env`. These are additive to the AC field list.
- `streaming.env` is optional and defaults to `Settings.env`.
- `fusion.relationships_report_path` has no default. Its real path is set per tenant by s32.
- `web/lib/env.ts` exports `publicEnv` as the AC says, but client components import it from
  `web/lib/env.public.ts`, because `env.ts` is `server-only`.
- `.env.example` lists pods with the key `DEV` only. The coverage test substitutes `<POD>` with `DEV`.
