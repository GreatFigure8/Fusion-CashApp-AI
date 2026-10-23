# s27-settings-secrets-wiring: Application settings and secrets wiring

- Issue: #27
- Wave: 1 (serialized spine, step 2 of 6)
- breaking: false

## Story

As an operator, I want one typed settings object for `api/` and one for `web/`, with secrets resolved from OCI Vault when deployed and from the environment locally, so that no secret ever sits in code or in `NEXT_PUBLIC_*`.

## Context

Follows `python-web-app:wiring-application-config`. Deploy-time settings only; business-tunable values are s28. research.md: secrets resolve through a `SecretSource` interface with exactly two implementations (Vault, env/fake).

## Acceptance criteria

1. [unit] `cashapp/settings.py` defines `Settings(BaseSettings)` with nested groups `atp` (dsn, user, password: SecretStr, wallet_dir|None, pool sizes), `streaming` (bootstrap_servers, sasl_username, sasl_password: SecretStr, topic_prefix, consumer_group, env), `object_storage` (namespace, bucket, region), `anthropic` (api_key: SecretStr, base_url|None), `oci_genai` (endpoint, compartment_ocid, dedicated_endpoint_ocid), `identity` (issuer, jwks_url, audience, groups_claim = "groups", bootstrap_admin_group = "CashApp-Admins"), `fusion` (pods: dict[str, FusionPodSettings{base_url, username, password: SecretStr, is_production: bool}], default_pod, write_enabled: bool = False), `observability` (log_level, otlp_endpoint|None, oci_monitoring_namespace), `worker` (health_port). `env: Literal["local","dev","test","prod"]`.
2. [unit] Missing required values fail fast at startup with one error listing every missing field name (never values).
3. [unit] `cashapp/secrets.py` defines `SecretSource` Protocol `async def resolve(self, ref: str) -> str` with `VaultSecretSource` (OCI SDK `SecretsClient.get_secret_bundle`, run via `asyncio.to_thread`, base64-decoded) and `EnvSecretSource`; any settings value of the form `vault:<secret-ocid>` is resolved once at startup by `load_settings() -> Settings` (Vault when `env != "local"`).
4. [unit] `get_settings()` is a cached accessor used by `main.py`, the Alembic `env.py` and the worker host; Alembic reads `atp` settings from it.
5. [unit] `web/lib/env.ts` validates server env with Zod at boot (`OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `SESSION_SECRET` (≥32 chars), `API_BASE_URL`, `APP_BASE_URL`) and exports `serverEnv` (imported only from server code, `import "server-only"`) and `publicEnv` (only `NEXT_PUBLIC_ENV_LABEL`); boot fails with the list of missing names.
6. [unit] `api/.env.example` and `web/.env.example` list every setting with placeholder values only; a test asserts every `Settings` field appears in `api/.env.example`.
7. [unit] No secret value appears in `repr(settings)` or logs (SecretStr), asserted by a test.

## Out of scope

Runtime/business configuration (s28); Vault provisioning (s25).

## Deps

- s01-scaffold-monorepo — `cashapp/` package, `pydantic-settings`, `oci` pinned; `main.py` and `alembic/env.py` exist. plannable.

## Test-support files owned

`api/tests/support/settings.py`: `make_settings(**overrides) -> Settings` (local env, fake values), used by every later API test.

## Assumptions

- Web OIDC client secret arrives as an env var injected from Vault by the deploy (s44); web reads env only.
