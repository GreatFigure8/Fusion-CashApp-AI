# Plan: db-stored-settings

Story: [story.md](story.md). Deps: none. Breaking: `CASHAPP_*` env contract reduced to the bootstrap set.
Skills applied: python-web-app:building-python-web-apps (layering, config refuses to boot on a missing value), python-web-app:wiring-application-config (closed surface, both ends of every key, bool-before-int, falsy-is-not-missing, bootstrap logging order, no inert keys), nextjs-fullstack-standards + BMN nextjs.md only for the regenerated web API types (rule ids: TS-5, TS-19, SEC-8, SEC-37, SEC-38). No design screen owned (Settings board is settings-screen-redesign's).

## 1 Approach

- research.md treats the existing ConfigService (`services/config.py`, `domain/config_keys.py`, `PUT /config/{key}` with reason, `expected_version`, Principal audit) as the one settings path (research.md a3 "propose-only config change", engine "throttle ... through the existing ConfigService"). This story moves every non-bootstrap deploy setting onto that path; it adds no second store or write path.
- `Settings` (settings.py) shrinks to `env`, `atp`, `worker.health_port`, `secrets` (secret-source selection). It stays the only module that reads the process environment. A strict scan rejects any other `CASHAPP_*` name, naming the DB key it moved to.
- `ConfigKey` gains `restart_required` and `secret_ref`. A `SecretRef` type only accepts Vault secret OCIDs. New group blocks hold the audited keys. `CONFIG_GROUPS` gives every group a label, an order and a description.
- `RuntimeSettings` (services/runtime_settings.py) wraps `RuntimeConfig`. Hot keys go through its TTL cache. Restart-required keys are pinned once by `start()`. Secrets are resolved at use through `secrets.SecretResolver`, which keeps a TTL cache and never logs. Factories, workers, pollers, the relay and the API take `RuntimeSettings` instead of `settings.<group>`.
- One Alembic data migration seeds the keys from the legacy env of the process that runs it. Settings exposes that env through `read_legacy_seed()`. The migration fails, naming every missing value, rather than seed an empty one.
- API: `GET /config` gets additive fields, plus `GET /config/groups`. ConfigWriter suffixes the history reason of a restart-required key.

## 2 Files to create / change

API (`api/src/cashapp/`)
| File | Change |
|---|---|
| `settings.py` | Keep `AtpSettings`. `WorkerBootstrapSettings{health_port}`. New `SecretSourceSettings{source: Literal["vault","env"] \| None = None (None: env when `env == "local"`, else vault), signer: Literal["resource_principal","instance_principal"] \| None = None (None: auto from `OCI_RESOURCE_PRINCIPAL_VERSION`), local_values: dict[str, SecretStr] = {} (only allowed when env is local; maps OCID to value)}`. `Settings` fields are exactly `env, atp, worker, secrets`. Remove the streaming, object_storage, anthropic, oci_genai, identity, fusion, observability, intake and smtp groups and the `_default_streaming_env` validator. Add `BOOTSTRAP_ENV_NAMES`, `TOOL_ENV_NAMES = {"CASHAPP_IDENTIFIER_DENYLIST"}` (typer option of the anonymise CLI, not a setting), and `LEGACY_ENV_TO_KEY: Mapping[str, str]` (every removed env name, or pod pattern, mapped to its DB key). `_scan_environ(environ, *, allow_legacy)` raises `SettingsError(invalid=...)` naming each unknown `CASHAPP_*` and, for a legacy one, "moved to DB key <key>". `load_settings(*, allow_legacy_env=False, ...)`; only `alembic/env.py` passes True. `read_legacy_seed(environ=None) -> LegacySeed{values: dict[str, JsonValue], missing: list[str], plaintext_secrets: list[str]}`: `vault:<ocid>` becomes the OCID. `build_secret_source(settings) -> SecretSource` and `oci_signer(settings) -> Any` hold the env reads that used to sit in secrets.py, cluster_metrics.py, oci_cohere_client.py, storage/oci.py and observability/metrics.py. |
| `settings_placeholders.py` | Placeholders for the bootstrap set only. Add `placeholder_config_values() -> dict[str, JsonValue]` (fake values for every key in `REQUIRED_KEYS`, with OCID-shaped fake secret refs) for the openapi dump and test support. |
| `secrets.py` | `EnvSecretSource(values)` takes a mapping and has no `os.environ` default. `VaultSecretSource.from_signer(signer)` replaces `from_environment`. New `SecretResolver(source, *, ttl_seconds=300, clock=None)` with `async resolve(ref: str) -> SecretStr` (TTL cache per ref, single-flight lock) and `invalidate(ref=None)`. Errors keep naming only the OCID. |
| `domain/config_keys.py` | `ConfigKey` gains `restart_required: bool = False` and `secret_ref: bool = False`; `_key(..., restart_required=, secret_ref=)`. `SecretRef` = `Annotated[str, StringConstraints(pattern=VAULT_SECRET_OCID_PATTERN)]` with `VAULT_SECRET_OCID_PATTERN = r"^ocid1\.vaultsecret\.oc1\.[a-z0-9-]+\.[a-z0-9]{20,}$"`. `GroupSpec{label, description, order}` and `CONFIG_GROUPS: Mapping[str, GroupSpec]` cover every group, existing and new. `REQUIRED_KEYS: tuple[ConfigKey, ...]`: keys whose default is None but which every process needs (section 5). `FusionPod`, `FusionTestData` and `SmtpGroup` models for the JSON-typed keys. New key blocks in section 5. Registry build asserts: `secret_ref` keys have a SecretRef-typed `type`, every `key.group` is in `CONFIG_GROUPS`, and no secret key is named without `_ref`. |
| `services/config.py` | `ConfigEntryData` gains `restart_required`, `secret_ref`, `last_changed_at` (= latest change `changed_at`, else None), `last_changed_by` (= latest change `changed_by_name`, else None). `ConfigWriter.set` appends `RESTART_NOTE = " [takes effect on restart]"` to the stored reason when `key.restart_required` (stays within 1000 chars: `normalize_reason` truncates before the suffix). `list_config_groups() -> list[ConfigGroupData]`. `ConfigSnapshot` and `RuntimeConfig` are otherwise unchanged; `_bool_leaks` already enforces bool-not-int. |
| `services/runtime_settings.py` (new) | `RuntimeSettings`, the typed group views and `build_runtime_settings`. Contract in section 7. |
| `api/schemas/config.py` | `ConfigEntry` adds `restart_required: bool`, `secret_ref: bool`, `last_changed_at: datetime \| None`, `last_changed_by: str \| None`. New `ConfigGroupOut{group, label, count, description}`. Existing fields kept (additive). |
| `api/routers/config.py` | Adds `GET /config/groups` (CONFIG_READ), declared before `/config/{key}/history`. |
| `api/runtime_deps.py` (new) | `get_runtime_settings()` (the process singleton built in lifespan) and `RuntimeSettingsDep`. A 503 `settings_not_loaded` ApiError before `start()` has completed. |
| `api/deps.py`, `api/fusion_deps.py`, `api/llm_deps.py`, `api/storage_deps.py`, `api/routers/{backlog,exceptions,flow,llm_usage,reversal}.py`, `auth/deps.py` | Read through `RuntimeSettingsDep` (identity, fusion, LLM, storage, intake folder). `TokenValidator.from_config(IdentityConfig)`. |
| `main.py` | `create_app` takes the bootstrap `Settings`, runs `configure_logging_bootstrap()` (INFO, stderr), and gets a lifespan that builds the engine, then `RuntimeSettings.start()`, then `reconfigure_observability(runtime)`, then flushes the buffered loader warnings. Uvicorn serves nothing until the lifespan completes, which closes the unauthenticated window. |
| `observability/{__init__,logging,tracing,metrics}.py` | Split into `configure_logging_bootstrap()` and `reconfigure_observability(runtime: RuntimeSettings, service_name)`. The level is resolved before it is applied, and a bad value falls back to INFO with a warning. Metrics use `runtime.observability().oci_monitoring_namespace` and `oci_genai().compartment_ocid`. |
| `integrations/fusion/{factory,guard}.py` | `build_fusion_client(runtime)`. Pods come from `runtime.fusion().pods`. The pod password is read per call through `runtime.secret(pod.password_ref)`. `write_enabled` and `unapply_verified` are hot and read per apply. |
| `integrations/llm/{factory,cluster_metrics,oci_cohere_client}.py` | `build_llm_clients(runtime)`. The Anthropic client is rebuilt when the resolved key changes (resolved at call time through the resolver TTL). The OCI signer comes from `settings.oci_signer`. |
| `integrations/storage/{factory,oci}.py` | `build_object_store(runtime)`. `OciObjectStore.from_config(ObjectStorageConfig, signer)`. |
| `pipeline/{bus,kafka,events,retry,runner}.py`, `stations/{notify/consumer,receipt_arrived/__init__,validate/runner}.py` | `TopicNamer.from_config(StreamingConfig, env)`. The consumer group comes from `runtime.streaming().consumer_group`. The SASL password is resolved when the bus connects. The `events._default_namer` global is set by `RuntimeSettings.start()` through `set_default_namer()`. |
| `workers/{container,host,cli}.py` | `WorkerContainer(settings, runtime=...)` exposes `container.runtime`. `health_port` stays on bootstrap settings. `shutdown_grace_seconds` is read hot at shutdown. CLI: bootstrap load, engine, `await runtime.start()`, reconfigure logging, run. |
| `pollers/intake/sources.py`, `services/backlog/sources.py` | The drop folder comes from `runtime.intake_folder()`. `intake.poll_interval_seconds` stays a hot read (unchanged). |
| `services/notifications/{channel,reports}.py` | SMTP comes from `runtime.smtp()` (None means the email channel is off). The password is resolved at send. |
| `services/reports/service.py` | Keeps `get_settings().env` (bootstrap). |
| `tools/{backlog,preflight,testdata,receipt_signal_study}/*`, `evals/runner.py` | Load bootstrap settings, then `build_runtime_settings(...).start()`, then read fusion pods and testdata from `runtime.fusion()`. |
| `openapi_dump.py` | Uses the bootstrap placeholders. `RuntimeSettings` isn't started, because routes don't build at import. |
| `api/alembic/env.py` | `load_settings(allow_legacy_env=True)`. |
| `api/alembic/versions/0002_group_role_mapping.py` | Replace `get_settings().identity.bootstrap_admin_group` with the literal `"CashApp-Admins"` (`BOOTSTRAP_ADMIN_GROUP` constant in `auth/`). Already-applied databases are unaffected (Assumptions). |
| `api/alembic/versions/s48_db_stored_settings.py` (new) | Data migration (section 4). |
| `api/.env.example` | Bootstrap set only: `CASHAPP_ENV`, `CASHAPP_ATP__*`, `CASHAPP_WORKER__HEALTH_PORT`, `CASHAPP_SECRETS__SOURCE`, `CASHAPP_SECRETS__SIGNER`, `CASHAPP_SECRETS__LOCAL_VALUES`, plus a comment pointing to docs/reference/settings.md. |
| `api/tests/support/settings.py` | Bootstrap placeholders, plus `FakeRuntimeSettings`/`runtime_settings_for(values)` built over an in-memory `ConfigStore`, and a fake `SecretSource`. |

Infra / deploy / docs
| File | Change |
|---|---|
| `infra/envs/{dev,prod}/main.tf` | `api_env` keeps only `CASHAPP_ENV`, `CASHAPP_ATP__{DSN,USER,PASSWORD}` and `CASHAPP_SECRETS__SOURCE="vault"`. New `local.settings_seed_env` holds the removed names with the same values, `vault:` refs for secrets. Output `migration_env = merge(local.api_env, local.settings_seed_env)` is consumed only by the release migration container (`sensitive = true`). |
| `infra/envs/{dev,prod}/outputs.tf` | `migration_env` output. |
| `deploy/scripts/run_in_vcn.sh`, `.github/workflows/release.yml` (only the migration step) | The migration container takes its env from the `migration_env` output; app containers keep `api_env`. |
| `deploy/README.md` | Replace the `CASHAPP_FUSION__WRITE_ENABLED` paragraph: `fusion.write_enabled` is now a DB key set in Settings. Explain the one-time seed and that `settings_seed_env` can be emptied after the first release that applies `s48`. |
| `docs/reference/settings.md` (new) | Every key: group, type, default, restart flag, secret flag, description, generated from `CONFIG_KEYS` by `python -m cashapp.tools.settings_doc`. The bootstrap env table gives the reason for each. Also the tool env names and the web env (API_BASE_URL, OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET[_VAULT_OCID], SESSION_SECRET[_VAULT_OCID], APP_BASE_URL, NEXT_PUBLIC_ENV_LABEL, each with why it is needed before Next can call the API). |
| `api/src/cashapp/tools/settings_doc/__main__.py` (new) | Renders the key table of settings.md from the registry. The doc test compares it with the committed file. |
| `CLAUDE.md` | One line under Architecture: "All settings except the database connection (and the few bootstrap values listed in docs/reference/settings.md) are DB config keys, edited in Settings, versioned and audited." |

Web: `web/lib/api/openapi.json` and `web/lib/api/schema.d.ts` regenerated with `npm run api:sync` (generated only, TS-5 then tsc). `web/.env.example` doesn't change (audit in Assumptions).

## 3 Test plan (written and run only from step 5)

| AC | Test | Path | Type |
|---|---|---|---|
| 1 | `test_settings_field_set_is_bootstrap_only` | `api/tests/test_settings_bootstrap.py` | unit |
| 1 | `test_unknown_cashapp_var_fails_loudly_naming_it` | same | unit |
| 1 | `test_legacy_var_fails_naming_its_db_key` | same | unit |
| 1 | `test_allow_legacy_env_only_tolerates_legacy_names` | same | unit |
| 1 | `test_tool_env_names_are_tolerated` | same | unit |
| 1 | `test_local_values_rejected_outside_local_env` | same | unit |
| 2 | `test_every_story_table_key_is_registered_with_group_and_flags` | `api/tests/test_config_keys_settings.py` | unit |
| 2 | `test_secret_keys_reject_plain_text` (parametrized over every `secret_ref` key) | same | unit |
| 2 | `test_secret_ref_accepts_vault_ocid` | same | unit |
| 2 | `test_every_group_has_group_spec` | same | unit |
| 2 | `test_consumer_group_is_restart_required_admin_only` | same | unit |
| 2 | `test_fusion_pods_shape_has_password_ref_not_password` | same | unit |
| 3 | `test_runtime_settings_hot_key_reads_through_cache` | `api/tests/test_runtime_settings.py` | unit |
| 3 | `test_restart_required_key_pinned_at_start` | same | unit |
| 3 | `test_start_fails_naming_every_missing_required_key` | same | unit |
| 3 | `test_partial_smtp_group_fails_start_naming_fields` | same | unit |
| 3 | `test_only_settings_module_reads_env` (static grep over `api/src` for `os.environ`, `getenv`, `load_dotenv`; allowlist: `settings.py`) | `api/tests/test_no_env_reads.py` | unit |
| 3 | `test_no_settings_group_attribute_reads_remain` (static grep for `settings\.(streaming\|object_storage\|anthropic\|oci_genai\|identity\|fusion\|observability\|intake\|smtp)`) | same | unit |
| 4 | `test_seed_migration_upgrade_seeds_from_env` | `api/tests/atp/test_s48_seed_migration.py` | integration (`-m atp`) |
| 4 | `test_seed_migration_downgrade_removes_seeded_rows` | same | integration (`-m atp`) |
| 4 | `test_seed_migration_fails_naming_every_missing_value` | same | integration (`-m atp`) |
| 4 | `test_read_legacy_seed_maps_vault_refs_and_pods` | `api/tests/test_legacy_seed.py` | unit |
| 4 | `test_read_legacy_seed_reports_plaintext_secret` | same | unit |
| 5 | `test_secret_resolver_caches_within_ttl_and_refreshes_after` | `api/tests/test_secret_resolver.py` | unit |
| 5 | `test_secret_resolver_errors_name_ocid_only` | same | unit |
| 5 | `test_secret_value_never_logged` (caplog over start + resolve + a failed resolve) | same | unit |
| 5 | `test_get_config_and_history_contain_no_resolved_secret` | `api/tests/api/test_config_router_settings.py` | api |
| 6 | `test_get_config_entries_have_new_fields` | same | api |
| 6 | `test_get_config_groups_counts_match_registry` | same | api |
| 6 | `test_get_config_groups_requires_config_read` | same | api |
| 6 | `test_openapi_has_config_groups_and_entry_fields` (dumped schema) | `api/tests/test_openapi_contract.py` | unit |
| 7 | `test_put_config_secret_key_plaintext_is_422` | `api/tests/api/test_config_router_settings.py` | api |
| 7 | `test_bool_rejected_for_int_key` (`worker.shutdown_grace_seconds: true` -> 422) | `api/tests/test_config_writer_settings.py` | unit |
| 7 | `test_falsy_valid_values_stored_not_defaulted` (`fusion.write_enabled=false`, `smtp.port` / int key `0` where allowed, empty list key) | same | unit |
| 7 | `test_put_requires_reason_expected_version_and_audits_principal` | same | unit |
| 8 | `test_poll_interval_change_applies_next_loop_without_restart` | `api/tests/test_runtime_settings_hot_reload.py` | unit |
| 8 | `test_restart_required_change_history_says_takes_effect_on_restart` | same | unit |
| 8 | `test_workers_pollers_relay_api_receive_runtime_settings` (container, intake poller, relay, `create_app` lifespan wiring) | same | unit |
| 8 | `test_api_refuses_requests_before_settings_loaded` (503 `settings_not_loaded`) | `api/tests/api/test_runtime_deps.py` | api |
| 9 | `test_settings_doc_lists_every_key_and_bootstrap_env` (regenerate and compare) | `api/tests/test_settings_doc.py` | unit |
| 9 | `test_claude_md_has_settings_line` | same | unit |
| 10 | `test_env_example_holds_only_bootstrap_names` | `api/tests/test_env_templates.py` | unit |
| 10 | `test_infra_api_env_has_only_bootstrap_names` (parses `infra/envs/*/main.tf` `api_env` keys) | same | unit |

Total: 44 named tests. Browser criteria: none (no screen owned; the Settings board's Playwright tests belong to settings-screen-redesign).

## 4 Data

- No new tables or columns. Existing `CONFIG_SETTING` and `CONFIG_CHANGE` hold the seeded rows.
- Migration: `api/alembic/versions/s48_db_stored_settings.py`, `revision = "s48_db_stored_settings"`. In split.md's merge order it comes after chat-agent-tool-registry, so the coder sets `down_revision = "s41_report_run"` (the current single head) and the merger re-points it to chat-agent-tool-registry's revision. Exactly one head. DEV ATP only, never run by the coder.
  - upgrade: `seed = read_legacy_seed()`. If `seed.missing` or `seed.plaintext_secrets` is non-empty, raise `RuntimeError` listing every env name and its DB key. A key that already has a `CONFIG_SETTING` row is skipped (re-run safe). Each value is validated with `validate_value(key, ...)` before insert. Rows are inserted `version=1`, `updated_by="system:seed"`, with a `CONFIG_CHANGE` row (`changed_by="system:seed"`, `changed_by_name="Seed (db-stored-settings)"`, `reason="Seeded from deploy environment by db-stored-settings"`).
  - downgrade: delete the `CONFIG_SETTING` rows of the seeded key list where `updated_by="system:seed"` and `version=1`, plus their seed `CONFIG_CHANGE` rows. Later admin edits are kept, and the downgrade logs a warning naming them.
  - Local: secret values come from `CASHAPP_SECRETS__LOCAL_VALUES`, so local `.env` secrets must be OCID-shaped refs. A plaintext legacy secret fails the seed with a pointer to this.

## 5 Config / env

Bootstrap env (stays): `CASHAPP_ENV`; `CASHAPP_ATP__{DSN,USER,PASSWORD,WALLET_DIR,WALLET_PASSWORD,POOL_SIZE,MAX_OVERFLOW,POOL_TIMEOUT_SECONDS}`; `CASHAPP_WORKER__HEALTH_PORT`; `CASHAPP_SECRETS__{SOURCE,SIGNER,LOCAL_VALUES}`. Read through settings.py: `OCI_RESOURCE_PRINCIPAL_VERSION` (platform-injected). Tool-only: `CASHAPP_IDENTIFIER_DENYLIST`. Web env unchanged.

New DB keys. R = restart_required, S = secret_ref, Req = in `REQUIRED_KEYS`. All are admin_only_write.
- `streaming.bootstrap_servers` str|None R Req; `streaming.sasl_username` str|None R Req; `streaming.sasl_password_ref` SecretRef|None R S Req; `streaming.topic_prefix` str "cashapp" R; `streaming.consumer_group` str|None R Req. Its description says "never rename or reset".
- `object_storage.namespace`, `object_storage.bucket` str|None R Req. Region stays a code constant (us-ashburn-1).
- `anthropic.base_url` str|None None R; `anthropic.api_key_ref` SecretRef|None R S Req.
- `oci_genai.endpoint` str (Ashburn URL) R; `oci_genai.compartment_ocid`, `oci_genai.dedicated_endpoint_ocid` str|None R Req; `oci_genai.dedicated_cluster_ocid` str|None None; `oci_genai.cluster_metric_namespace` str "oci_generativeai"; `oci_genai.cluster_metric_query` str|None None.
- `identity.issuer`, `identity.jwks_url`, `identity.audience` str|None R Req; `identity.groups_claim` str "groups" R.
- `fusion.pods` dict[str, FusionPod] {} R Req (non-empty, lower-cased keys). `FusionPod{base_url, username, password_ref: SecretRef, is_production: bool=False, testdata: FusionTestData|None=None, mcp_source: str|None=None}`. `fusion.default_pod` str|None R Req (must be a pods key; checked at start). `fusion.write_enabled` bool False (hot). `fusion.unapply_verified` bool False (hot). `fusion.relationships_report_path` str|None Req (hot).
- `observability.log_level` Literal DEBUG/INFO/WARNING/ERROR "INFO" R; `observability.otlp_endpoint` str|None None R; `observability.oci_monitoring_namespace` str "cashapp" R.
- `worker.shutdown_grace_seconds` int ge 1, 30 (hot).
- `intake.drop_folder` str|None R Req.
- `smtp.host` str|None None R (None means email is off); `smtp.port` int 1..65535, 587 R; `smtp.username` str|None R; `smtp.from_address` str|None R; `smtp.password_ref` SecretRef|None R S. All or none: start fails on a partial group.

New `CONFIG_GROUPS` entries: streaming "Event bus", object_storage "Object Storage", anthropic "Claude API", oci_genai "OCI Generative AI", identity "Sign-in", fusion "Fusion", observability "Observability", worker "Workers", smtp "Email (SMTP)". Plus labels for every existing group: intake "Pollers: intake", receipt_watcher "Pollers: receipt watcher", matching "Matching", retries "Auto-fix retries", aging "Aging", escalation "Escalation", models "Models", extraction "Extraction", concurrency "Concurrency", locks "Locks", backlog "Backlog", retention "Retention", budget "Budget", notifications "Notifications", reports "Reports", discount "Discounts".

## 6 Risks and gates

- Risk: the release migration has no legacy env once infra drops it. Mitigation: the `migration_env` output feeds only the migration container. If a value is missing, the seed fails loudly and the deploy aborts before the app rolls out.
- Risk: identity in the DB means the API needs ATP before it can authenticate. Mitigation: the lifespan blocks serving, and the dependency returns 503 before start.
- Risk: wide refactor across about 40 modules, colliding with fusion-mcp-transport (integrations/fusion/*) and engine-control-api (pipeline/*). Mitigation: merge order puts this story first among them, and they code against the pinned `RuntimeSettings` contract below.
- Risk: `streaming.consumer_group` must never change. Mitigation: R + admin-only, the description warns, and the seed copies the existing value byte for byte.
- Risk: editing applied migration 0002. Mitigation: same default literal, no behaviour change on fresh DBs that used the default.
- Coder gates: lint + type-check only. api: `cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`. web (regenerated types only): `cd web && npx eslint . && npx next typegen && npx tsc --noEmit`. Run `npm run api:sync` (after `npm ci`) to regenerate the OpenAPI JSON and types.

## 7 Interfaces provided (pinned)

```python
# cashapp/domain/config_keys.py
@dataclass(frozen=True)
class ConfigKey[T]:
    name: str; group: str; type: Any; default: T; description: str
    admin_only_write: bool = True
    restart_required: bool = False
    secret_ref: bool = False
def _key[T](name, tp, default: T, description, *, admin_only_write=True,
            restart_required=False, secret_ref=False) -> ConfigKey[T]
SecretRef = Annotated[str, StringConstraints(pattern=VAULT_SECRET_OCID_PATTERN)]
@dataclass(frozen=True)
class GroupSpec: label: str; description: str; order: int
CONFIG_GROUPS: Mapping[str, GroupSpec]   # append-only dict literal, one entry per group
class FusionPod(BaseModel, frozen=True):
    base_url: str; username: str; password_ref: SecretRef
    is_production: bool = False; testdata: FusionTestData | None = None; mcp_source: str | None = None
FUSION_PODS: ConfigKey[dict[str, FusionPod]]; FUSION_DEFAULT_POD: ConfigKey[str | None]
FUSION_WRITE_ENABLED: ConfigKey[bool]
# A story adding keys appends a block of _key(...) constants and adds them to _ALL_KEYS, plus a
# CONFIG_GROUPS entry for a new group (chat, mcp, engine, uploads, review, lab).

# cashapp/services/runtime_settings.py
class RuntimeSettings:
    def __init__(self, config: RuntimeConfig, resolver: SecretResolver, *, env: str) -> None
    async def start(self) -> None                  # pins restart_required keys, checks REQUIRED_KEYS; idempotent
    @property
    def started(self) -> bool
    async def get[T](self, key: ConfigKey[T]) -> T  # hot: RuntimeConfig cache; restart_required: pinned value
    def pinned[T](self, key: ConfigKey[T]) -> T     # sync; restart_required keys only, after start()
    async def secret(self, key_or_ref: ConfigKey[str | None] | str) -> SecretStr   # resolved at use, TTL-cached
    def streaming(self) -> StreamingConfig           # pinned views (frozen dataclasses)
    def object_storage(self) -> ObjectStorageConfig
    def anthropic(self) -> AnthropicConfig
    def oci_genai(self) -> OciGenAiConfig
    def identity(self) -> IdentityConfig
    def fusion(self) -> FusionConfig                 # pods, default_pod (pinned)
    async def fusion_writes(self) -> FusionWriteFlags  # write_enabled, unapply_verified (hot)
    def observability(self) -> ObservabilityConfig
    def intake_folder(self) -> Path
    def smtp(self) -> SmtpConfig | None
    @property
    def config(self) -> RuntimeConfig                # existing typed snapshots (matching, models...)
def build_runtime_settings(settings: Settings, uow_factory: UowFactory, *, clock: Clock | None = None) -> RuntimeSettings
# cashapp/api/runtime_deps.py
RuntimeSettingsDep = Annotated[RuntimeSettings, Depends(get_runtime_settings)]
```

HTTP (additive):
- `GET /config` -> `list[ConfigEntry]`, where `ConfigEntry = {key, group, description, value, default, version, updated_by, updated_by_name, updated_at, admin_only_write, restart_required: bool, secret_ref: bool, last_changed_at: datetime|null, last_changed_by: str|null}`. For a `secret_ref` key, `value` is the OCID or null and never the secret. `last_changed_by` is null for an unchanged default; the seed shows "Seed (db-stored-settings)".
- `GET /config/groups` (CONFIG_READ) -> `list[ConfigGroupOut{group: str, label: str, count: int, description: str}]`, sorted by `GroupSpec.order` and then by group.
- `PUT /config/{key}` unchanged (`{value, reason, expected_version}`). For a restart-required key, the history `reason` ends with ` [takes effect on restart]`.

| Consumer | Contract | Plannable |
|---|---|---|
| fusion-mcp-transport | `ConfigKey.secret_ref/restart_required`, `_key(...)` kwargs, `SecretRef`, `RuntimeSettings.get/secret/fusion()`, `FUSION_PODS` with `FusionPod.mcp_source` already present, `CONFIG_GROUPS` entry for `mcp` | true |
| settings-screen-redesign | `GET /config` entry fields above, `GET /config/groups` shape, restart history suffix | true |
| failed-receipt-review | `_key(...)` with flags, `CONFIG_GROUPS` append, `RuntimeSettings.get(key)` | true |
| matching-lab-replay-api | same as failed-receipt-review for `lab.*` | true |

## Assumptions

- Secret-source selection lives in the bootstrap group `secrets` (`source`, `signer`, `local_values`). Local secrets map fake OCIDs to values in `CASHAPP_SECRETS__LOCAL_VALUES`, so `SecretRef` stays strict everywhere.
- The `OCI_RESOURCE_PRINCIPAL_VERSION` reads in five modules are consolidated into `settings.oci_signer()`. That keeps settings.py the only env reader (AC3), and removes duplicated code (non-negotiable 7).
- `identity.bootstrap_admin_group` is not created as a DB key. Its only reader is migration 0002, which already seeded the admin mapping, so a DB key would be inert (wiring-application-config). 0002 uses the same default literal. This deviates from the story table.
- No third spec flag for "required". `REQUIRED_KEYS` lists keys whose default is None but which every process must have; `start()` fails naming them all.
- `streaming.env` is dropped. The topic env is the bootstrap `env`, which is what the existing validator defaulted it to.
- Restart-required keys: everything read when clients are constructed. Hot keys: fusion write and unapply flags, the relationships report path, cluster metric settings, `worker.shutdown_grace_seconds`.
- The "takes effect on restart" note is a reason suffix rather than a new column, so the migration stays data-only.
- Web env audit: `API_BASE_URL`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET(_VAULT_OCID)`, `SESSION_SECRET(_VAULT_OCID)`, `APP_BASE_URL` (OIDC redirect origin, needed before any API call) and `NEXT_PUBLIC_ENV_LABEL` (inlined at build, SEC-38) all stay. The story's allowed list omitted `OIDC_ISSUER`, `APP_BASE_URL` and the label, but sign-in needs them before a token exists. No web env change.
- The release migration reads the legacy values from a migration-only Terraform output. The workflow change is limited to the migration step, and nothing deploys during the run.
- `FusionPod.mcp_source` is included now (optional), so fusion-mcp-transport fills it without reshaping the key.
