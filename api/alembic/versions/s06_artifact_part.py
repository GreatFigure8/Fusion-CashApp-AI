"""s06: ARTIFACT_PART (the normalised parts of a work item's artifact).

Revision ID: s06_artifact_part
Revises: 0003_config
"""

import sqlalchemy as sa
from alembic import op

revision = "s06_artifact_part"
# Written against s28's head; the merger re-points this and checks for a single head.
down_revision = "0003_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_part",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column(
            "work_item_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column("part_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(1000), nullable=False),
        sa.Column("source_path", sa.String(1000), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("text_preview_chars", sa.Integer(), nullable=True),
        sa.Column("purged_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_ARTIFACT_PART"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_item.id"], name="FK_ARTIFACT_PART_ITEM"),
        sa.UniqueConstraint("work_item_id", "part_no", name="UQ_ARTIFACT_PART_ITEM_NO"),
    )


def downgrade() -> None:
    op.drop_table("artifact_part")
