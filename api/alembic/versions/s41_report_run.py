"""s41: REPORT_RUN (one stored report per kind and day).

Revision ID: s41_report_run
Revises: s45_retention_purge
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision = "s41_report_run"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision = "s35_backlog_batch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_run",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("generated_at", UtcDateTime(), nullable=False),
        sa.Column("generated_by", sa.String(255), nullable=False),
        sa.Column("generated_by_name", sa.String(255), nullable=False),
        sa.Column("payload", JsonDoc(), nullable=False),
        sa.Column("emailed_to", JsonDoc(), nullable=True),
        sa.Column("emailed_at", UtcDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_REPORT_RUN"),
        sa.UniqueConstraint("kind", "report_date", name="UQ_REPORT_RUN_KIND_DATE"),
    )


def downgrade() -> None:
    op.drop_table("report_run")
