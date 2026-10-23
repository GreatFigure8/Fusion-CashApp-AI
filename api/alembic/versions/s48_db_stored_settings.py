"""s48: seed the DB config keys that replace the removed deploy environment variables.

Data migration only: no table or column changes. It reads the legacy `CASHAPP_*` variables of the
process that runs it (on DEV that keeps the running pods working), validates each value with the
key's own type and writes one `CONFIG_SETTING` row and one `CONFIG_CHANGE` row per key. It fails,
naming every missing or plain-text value, rather than seed an empty one. Re-running skips keys
that already have a row.

Revision ID: s48_db_stored_settings
Revises: ui01_chat_agent_tool_registry
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime
from cashapp.domain.config_keys import CONFIG_KEYS
from cashapp.services.config import ConfigValidationError, to_json, validate_value
from cashapp.settings import legacy_env_name, read_legacy_seed, seed_key_names

revision: str = "s48_db_stored_settings"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision: str | None = "ui01_chat_agent_tool_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

SEED_ACTOR = "system:seed"
SEED_ACTOR_NAME = "Seed (db-stored-settings)"
SEED_REASON = "Seeded from deploy environment by db-stored-settings"

_setting = sa.table(
    "config_setting",
    sa.column("key", sa.String),
    sa.column("value", JsonDoc()),
    sa.column("version", sa.Integer),
    sa.column("updated_at", UtcDateTime()),
    sa.column("updated_by", sa.String),
)
_change = sa.table(
    "config_change",
    sa.column("key", sa.String),
    sa.column("old_value", JsonDoc()),
    sa.column("new_value", JsonDoc()),
    sa.column("changed_by", sa.String),
    sa.column("changed_by_name", sa.String),
    sa.column("changed_at", UtcDateTime()),
    sa.column("reason", sa.String),
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {row[0] for row in bind.execute(sa.select(_setting.c.key))}
    seed = read_legacy_seed()

    problems: list[str] = []
    problems.extend(
        f"{legacy_env_name(name)} is not set (DB key {name})"
        for name in seed.missing
        if name not in existing
    )
    problems.extend(
        f"{name} holds a plain-text secret; give it as vault:<secret-ocid> "
        "(locally, map the OCID in CASHAPP_SECRETS__LOCAL_VALUES)"
        for name in seed.plaintext_secrets
    )
    prepared: dict[str, object] = {}
    for name, raw in seed.values.items():
        if name in existing:
            continue
        key = CONFIG_KEYS[name]
        try:
            prepared[name] = to_json(key, validate_value(key, raw))
        except ConfigValidationError as exc:
            problems.append(f"{legacy_env_name(name)} -> {name} is invalid: {exc}")
    if problems:
        raise RuntimeError("Cannot seed the DB settings:\n  " + "\n  ".join(problems))

    now = datetime.now(UTC)
    for name, value in prepared.items():
        bind.execute(
            _setting.insert().values(
                key=name, value=value, version=1, updated_at=now, updated_by=SEED_ACTOR
            )
        )
        bind.execute(
            _change.insert().values(
                key=name,
                old_value=None,
                new_value=value,
                changed_by=SEED_ACTOR,
                changed_by_name=SEED_ACTOR_NAME,
                changed_at=now,
                reason=SEED_REASON,
            )
        )
    log.info("s48: seeded %d settings from the deploy environment", len(prepared))


def downgrade() -> None:
    bind = op.get_bind()
    names = seed_key_names()
    edited = bind.execute(
        sa.select(_setting.c.key).where(
            _setting.c.key.in_(names),
            sa.or_(_setting.c.updated_by != SEED_ACTOR, _setting.c.version != 1),
        )
    )
    kept = sorted(row[0] for row in edited)
    if kept:
        log.warning("s48 downgrade keeps settings that were edited after the seed: %s", kept)
    bind.execute(
        sa.delete(_setting).where(
            _setting.c.key.in_(names),
            _setting.c.updated_by == SEED_ACTOR,
            _setting.c.version == 1,
        )
    )
    bind.execute(
        sa.delete(_change).where(_change.c.key.in_(names), _change.c.changed_by == SEED_ACTOR)
    )
