"""s48: REPORT_EXPORT (log of exported HTML progress reports).

Revision ID: s48_report_export
Revises: s48_mcp_call_log
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision = "s48_report_export"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision = "s48_mcp_call_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_export",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("window", sa.String(8), nullable=False),
        sa.Column("sections", JsonDoc(), nullable=False),
        sa.Column("filename", sa.String(120), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_REPORT_EXPORT"),
    )
    op.create_index("IX_REPORT_EXPORT_AT", "report_export", ["at"])


def downgrade() -> None:
    op.drop_index("IX_REPORT_EXPORT_AT", table_name="report_export")
    op.drop_table("report_export")
