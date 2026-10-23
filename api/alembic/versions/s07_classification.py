"""s07: CLASSIFICATION (one row per classify decision, model or human).

Revision ID: s07_classification
Revises: s06_artifact_part
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import UtcDateTime

revision = "s07_classification"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision = "s06_artifact_part"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classification",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column(
            "work_item_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column("is_remittance", sa.Boolean(create_constraint=False), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("model_id", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(20), nullable=True),
        sa.Column("origin", sa.String(40), nullable=False),
        sa.Column("decided_by", sa.String(256), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_CLASSIFICATION"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_item.id"], name="FK_CLASSIFICATION_WI"),
    )
    op.create_index("IX_CLASSIFICATION_ITEM_AT", "classification", ["work_item_id", "created_at"])


def downgrade() -> None:
    op.drop_index("IX_CLASSIFICATION_ITEM_AT", table_name="classification")
    op.drop_table("classification")
