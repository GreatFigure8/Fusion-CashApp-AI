"""s37: PAYER_ALIAS (learned payer name, bank account and reference-pattern aliases).

Revision ID: s37_payer_alias
Revises: s06_artifact_part
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import UtcDateTime

revision: str = "s37_payer_alias"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision: str | None = "0005_s09_adjudication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payer_alias",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("payer_name_norm", sa.String(500), nullable=True),
        sa.Column("payer_bank_account", sa.String(100), nullable=True),
        sa.Column("reference_pattern", sa.String(200), nullable=True),
        sa.Column("customer_account_number", sa.String(100), nullable=False),
        sa.Column("learned_from_item_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_by_name", sa.String(255), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("uses", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_used_at", UtcDateTime(), nullable=True),
        sa.Column("retired_at", UtcDateTime(), nullable=True),
        sa.Column("retired_by", sa.String(255), nullable=True),
        sa.Column("retire_reason", sa.String(1000), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_PAYER_ALIAS"),
    )
    op.create_index("IX_PAYER_ALIAS_NAME_NORM", "payer_alias", ["payer_name_norm"])
    op.create_index("IX_PAYER_ALIAS_BANK_ACCOUNT", "payer_alias", ["payer_bank_account"])
    op.create_index("IX_PAYER_ALIAS_CUSTOMER", "payer_alias", ["customer_account_number"])


def downgrade() -> None:
    op.drop_index("IX_PAYER_ALIAS_CUSTOMER", table_name="payer_alias")
    op.drop_index("IX_PAYER_ALIAS_BANK_ACCOUNT", table_name="payer_alias")
    op.drop_index("IX_PAYER_ALIAS_NAME_NORM", table_name="payer_alias")
    op.drop_table("payer_alias")
