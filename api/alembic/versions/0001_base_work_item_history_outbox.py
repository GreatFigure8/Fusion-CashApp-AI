"""Base tables: WORK_ITEM, WORK_ITEM_HISTORY, OUTBOX.

Revision ID: 0001_base
Revises:
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision: str = "0001_base"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[int]:
    return sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "work_item",
        _id(),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("source_ref", sa.String(1000), nullable=True),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("artifact_key", sa.String(1000), nullable=True),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(40), nullable=True),
        sa.Column("last_error_detail", JsonDoc(), nullable=True),
        sa.Column("escalation_summary", sa.Text(), nullable=True),
        sa.Column("claim_expires_at", UtcDateTime(), nullable=True),
        sa.Column("lock_owner", sa.String(255), nullable=True),
        sa.Column("lock_owner_name", sa.String(255), nullable=True),
        sa.Column("lock_acquired_at", UtcDateTime(), nullable=True),
        sa.Column("lock_expires_at", UtcDateTime(), nullable=True),
        sa.Column("payer_name", sa.String(500), nullable=True),
        sa.Column("customer_account_number", sa.String(100), nullable=True),
        sa.Column("currency", sa.CHAR(3), nullable=True),
        sa.Column("payment_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("payment_status", sa.String(40), nullable=True),
        sa.Column("info_flags", JsonDoc(), nullable=False),
        sa.Column("human_hints", JsonDoc(), nullable=True),
        sa.Column("fix_hints", JsonDoc(), nullable=True),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("awaiting_since", UtcDateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_WORK_ITEM"),
        sa.ForeignKeyConstraint(["parent_id"], ["work_item.id"], name="FK_WORK_ITEM_PARENT"),
        sa.UniqueConstraint("content_hash", name="UQ_WORK_ITEM_CONTENT_HASH"),
    )
    op.create_index("IX_WORK_ITEM_STAGE_STATE", "work_item", ["stage", "state"])
    op.create_index("IX_WORK_ITEM_STATE_AWAITING", "work_item", ["state", "awaiting_since"])
    op.create_index("IX_WORK_ITEM_LOCK_OWNER", "work_item", ["lock_owner"])
    op.create_index("IX_WORK_ITEM_PARENT_ID", "work_item", ["parent_id"])

    op.create_table(
        "work_item_history",
        _id(),
        sa.Column("work_item_id", sa.BigInteger(), nullable=False),
        sa.Column("at", UtcDateTime(), nullable=False),
        sa.Column("actor_kind", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("from_stage", sa.String(40), nullable=True),
        sa.Column("to_stage", sa.String(40), nullable=True),
        sa.Column("from_state", sa.String(40), nullable=True),
        sa.Column("to_state", sa.String(40), nullable=True),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("payload", JsonDoc(), nullable=True),
        sa.Column("purged_at", UtcDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_WORK_ITEM_HISTORY"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_item.id"], name="FK_WIH_WORK_ITEM"),
    )
    op.create_index("IX_WIH_ITEM_AT", "work_item_history", ["work_item_id", "at"])

    op.create_table(
        "outbox",
        _id(),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("msg_key", sa.String(255), nullable=False),
        sa.Column("payload", JsonDoc(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("not_before", UtcDateTime(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("published_at", UtcDateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_OUTBOX"),
    )
    op.create_index("IX_OUTBOX_PENDING", "outbox", ["published_at", "not_before", "priority"])


def downgrade() -> None:
    op.drop_index("IX_OUTBOX_PENDING", table_name="outbox")
    op.drop_table("outbox")
    op.drop_index("IX_WIH_ITEM_AT", table_name="work_item_history")
    op.drop_table("work_item_history")
    op.drop_index("IX_WORK_ITEM_PARENT_ID", table_name="work_item")
    op.drop_index("IX_WORK_ITEM_LOCK_OWNER", table_name="work_item")
    op.drop_index("IX_WORK_ITEM_STATE_AWAITING", table_name="work_item")
    op.drop_index("IX_WORK_ITEM_STAGE_STATE", table_name="work_item")
    op.drop_table("work_item")
