# db-stored-settings: Every setting except the database connection lives in the database

- Issue: #48 (scope item 3)
- breaking: true (deploy contract: `CASHAPP_*` environment variables other than the bootstrap set are removed; values move to DB config keys seeded by migration)
- Design screen owned: none (API; the Settings screen is owned by settings-screen-redesign)

## Story

As an admin, I want every setting other than the database connection stored in the database, versioned, audited and editable in Settings, so that nothing needs a redeploy or a file edit to change and every change has a who and a why.

## Context

Jonathan: "all settings other than database connection information stored in the database like we always do". The config service already exists (`services/config.py`, `domain/config_keys.py`, `api/routers/config.py` with `GET /config`, `PUT /config/{key}`, history). Deploy-time settings live in `cashapp/settings.py` (`Settings` model, env `CASHAPP_<GROUP>__<FIELD>`, `vault:` refs resolved by `cashapp/secrets.py`). Load `python-web-app:wiring-application-config` (fail loudly on unknown or unread keys; falsy-but-valid values; bootstrap ordering).

Audit of `settings.py` today (what is still in env/files) and where each goes:

| Env group.field | Destination |
|---|---|
| `env` | stays env (bootstrap: picks the DB and the consumer-group suffix) |
| `atp.*` (dsn, user, password, wallet_dir, wallet_password, pool sizes) | stays env/Vault: **database connection info** |
| `streaming.bootstrap_servers, sasl_username, topic_prefix, consumer_group` | DB keys `streaming.*`; `sasl_password` becomes a DB key holding a Vault secret OCID (`SecretRef`), value resolved from Vault at use |
| `object_storage.namespace, bucket` (region fixed) | DB keys `object_storage.*` |
| `anthropic.base_url`; `anthropic.api_key` | DB `anthropic.base_url`; `anthropic.api_key_ref` (`SecretRef`) |
| `oci_genai.*` (endpoint, compartment_ocid, dedicated_endpoint_ocid, dedicated_cluster_ocid, cluster_metric_namespace, cluster_metric_query) | DB keys `oci_genai.*` |
| `identity.issuer, jwks_url, audience, groups_claim, bootstrap_admin_group` | DB keys `identity.*`; `bootstrap_admin_group` seeded from the migration so first sign-in still works |
| `fusion.pods.*` (base_url, username, password, is_production, testdata.*), `default_pod`, `write_enabled`, `unapply_verified`, `relationships_report_path` | DB keys `fusion.*` (pods as one JSON key, passwords as `SecretRef`); reads move to the MCP (fusion-mcp-transport), the SOAP apply keeps the pod base URL and credential ref |
| `observability.log_level, otlp_endpoint, oci_monitoring_namespace` | DB keys `observability.*` (logging starts at INFO, then reconfigures after the DB read; the loader's own warnings are buffered, not swallowed) |
| `worker.shutdown_grace_seconds` | DB key `worker.shutdown_grace_seconds` |
| `worker.health_port` | stays env (bootstrap: bound before the DB is reachable and pinned by the deployment manifest) |
| `intake.drop_folder` | DB key `intake.drop_folder` |
| `smtp.host, port, username, from_address`; `smtp.password` | DB keys `smtp.*`; `smtp.password_ref` (`SecretRef`) |
| Vault/secret source selection in `secrets.py` (how to reach Vault) | stays env (bootstrap) |

The planner re-runs this audit against the code (`git grep -n "CASHAPP_\|os.environ\|getenv\|\.env\|yaml\|toml" api/ web/ infra/ deploy/`) and adds any row this table misses, including `web/` env (only the API base URL, the OIDC client id/secret refs and the session cookie key may stay, because Next needs them before it can call the API).

## Acceptance criteria

1. [unit] `settings.py` `Settings` keeps only the bootstrap set (`env`, `atp`, `worker.health_port`, the secret-source selection); every other group is removed. A test asserts the model's field set equals that list and that `load_settings()` fails loudly on any other `CASHAPP_*` variable (extra="forbid" kept).
2. [unit] `config_keys.py` gains every destination key in the table with type, default, description, group, and two new spec flags: `restart_required: bool` (the value is read at process start; the UI says so) and `secret_ref: bool` (the value is a Vault secret OCID; the API never returns the resolved secret, and `GET /config` returns only the OCID). `SecretRef` values must match the Vault OCID pattern; a test rejects plain text in a secret key.
3. [unit] A runtime settings provider (`cashapp/services/runtime_settings.py`, `RuntimeSettings.get(key)` / typed accessors per group) replaces every former `settings.<group>` read; hot keys are read through the ConfigService cache, restart-required keys are read once at start. No module reads env except `settings.py` (static grep test).
4. [integration] One Alembic data migration seeds the new keys: on DEV it takes the values from the current environment the migration runs in (so DEV keeps working), and fails with a clear message naming every missing value instead of seeding an empty one. It applies and downgrades on the DEV ATP schema (`-m atp`).
5. [unit] Secrets are resolved through `cashapp/secrets.py` at use, cached with a TTL, never written to logs, history or API responses; a test asserts `GET /config` and the change history contain no resolved secret.
6. [api] `GET /config` entries gain `group`, `restart_required`, `secret_ref`, `last_changed_at`, `last_changed_by`; a new `GET /config/groups` returns `[{group, label, count, description}]` for the Settings group nav. Additive to the existing contract; OpenAPI regenerated.
7. [unit] Every write still goes through `PUT /config/{key}` (CONFIG_WRITE, reason, expected_version, Principal audit); `bool`-as-`int` and falsy-but-valid values (`0`, `false`, empty list) are validated, not defaulted.
8. [unit] Workers, pollers, the relay and the API all read through `RuntimeSettings`; changing `intake.poll_interval_seconds` in the DB takes effect on the next loop without a restart (existing behaviour kept), and changing a restart-required key records "takes effect on restart" in the history row.
9. [unit] `docs/reference/settings.md` lists every key, its group, default, restart flag, and the bootstrap env set with the reason each stays outside the DB; CLAUDE.md gets one line under Architecture recording "all settings except the database connection are DB config keys" and pointing to that doc.
10. [unit] `deploy/` and `infra/` env templates drop the removed variables; `.env.example` (or equivalent) holds only the bootstrap set.

## Out of scope

- The Settings UI (settings-screen-redesign). The `mcp.*` keys (fusion-mcp-transport owns them). Feature keys of other stories (each owns its own, split.md).

## Deps

None.

## Assumptions

- `streaming.consumer_group` becomes a DB key but its value is never renamed or reset (CLAUDE.md Bus); the key is `admin_only_write` and `restart_required`, and its description says so.
- `fusion.pods` stays one JSON key (shape of `FusionPodSettings` minus the password, plus `password_ref`) rather than one key per field.
- Identity keys being in the DB means the API reads them after connecting to ATP; the API refuses requests until they are loaded (no unauthenticated window).
