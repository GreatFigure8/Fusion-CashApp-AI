"""s45: RETENTION_PURGE (pending/confirmed marker for artifact purges).

Revision ID: s45_retention_purge
Revises: s36_llm_usage
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision = "s45_retention_purge"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision = "s36_llm_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retention_purge",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("work_item_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("object_keys", JsonDoc(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("confirmed_at", UtcDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_RETENTION_PURGE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_item.id"], name="FK_RETENTION_PURGE_ITEM"),
        sa.UniqueConstraint("work_item_id", "kind", name="UQ_RETENTION_PURGE_ITEM_KIND"),
    )
    op.create_index("IX_RETENTION_PURGE_STATUS", "retention_purge", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("IX_RETENTION_PURGE_STATUS", table_name="retention_purge")
    op.drop_table("retention_purge")
