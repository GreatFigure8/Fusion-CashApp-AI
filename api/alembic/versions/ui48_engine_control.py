"""ui48: ENGINE_AUDIT and ENGINE_DLQ_REPLAY (engine control: pause, throttle, dead-letter replay).

Revision ID: ui48_engine_control
Revises: s45_retention_purge
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision = "ui48_engine_control"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision = "s45_retention_purge"
branch_labels = None
depends_on = None


def _identity() -> sa.Column[int]:
    return sa.Column(
        "id",
        sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
        sa.Identity(),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "engine_audit",
        _identity(),
        sa.Column("at", UtcDateTime(), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("actor_role", sa.String(64), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("stations", JsonDoc(), nullable=False),
        sa.Column("before_state", JsonDoc(), nullable=True),
        sa.Column("after_state", JsonDoc(), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_ENGINE_AUDIT"),
    )
    op.create_index("IX_ENGINE_AUDIT_AT", "engine_audit", ["at"])
    op.create_table(
        "engine_dlq_replay",
        _identity(),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("outbox_id", sa.Integer(), nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("replayed_at", UtcDateTime(), nullable=False),
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_ENGINE_DLQ_REPLAY"),
        sa.ForeignKeyConstraint(
            ["audit_id"], ["engine_audit.id"], name="FK_ENGINE_DLQ_REPLAY_AUDIT"
        ),
        sa.UniqueConstraint("event_id", name="UQ_ENGINE_DLQ_REPLAY_EVENT"),
    )
    op.create_index("IX_OUTBOX_TOPIC_CREATED", "outbox", ["topic", "created_at"])


def downgrade() -> None:
    op.drop_index("IX_OUTBOX_TOPIC_CREATED", table_name="outbox")
    op.drop_table("engine_dlq_replay")
    op.drop_index("IX_ENGINE_AUDIT_AT", table_name="engine_audit")
    op.drop_table("engine_audit")
