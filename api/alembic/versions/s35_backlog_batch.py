"""s35: BACKLOG_BATCH and the foreign key WORK_ITEM.BATCH_ID -> BACKLOG_BATCH.ID.

Revision ID: s35_backlog_batch
Revises: s45_retention_purge
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision = "s35_backlog_batch"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision = "s45_retention_purge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backlog_batch",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("source_ref", sa.String(1000), nullable=False),
        sa.Column("dry_run", sa.Boolean(create_constraint=False), nullable=False),
        sa.Column("rate_limit_per_min", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_by_name", sa.String(255), nullable=True),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("started_at", UtcDateTime(), nullable=True),
        sa.Column("imported_at", UtcDateTime(), nullable=True),
        sa.Column("finished_at", UtcDateTime(), nullable=True),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.Column("import_error", sa.Text(), nullable=True),
        sa.Column("promoted_from_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite")),
        sa.Column("audit", JsonDoc(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_BACKLOG_BATCH"),
        sa.UniqueConstraint("name", name="UQ_BACKLOG_BATCH_NAME"),
        sa.ForeignKeyConstraint(
            ["promoted_from_id"], ["backlog_batch.id"], name="FK_BACKLOG_BATCH_PROMOTED"
        ),
    )
    op.create_index("IX_BACKLOG_BATCH_STATUS", "backlog_batch", ["status"])
    # Every existing BATCH_ID is NULL (nothing wrote it before), so the foreign key validates.
    with op.batch_alter_table("work_item") as batch_op:
        batch_op.create_foreign_key("FK_WORK_ITEM_BATCH_ID", "backlog_batch", ["batch_id"], ["id"])
        batch_op.create_index("IX_WORK_ITEM_BATCH_STATE", ["batch_id", "state"])


def downgrade() -> None:
    with op.batch_alter_table("work_item") as batch_op:
        batch_op.drop_index("IX_WORK_ITEM_BATCH_STATE")
        batch_op.drop_constraint("FK_WORK_ITEM_BATCH_ID", type_="foreignkey")
    op.drop_index("IX_BACKLOG_BATCH_STATUS", table_name="backlog_batch")
    op.drop_table("backlog_batch")
