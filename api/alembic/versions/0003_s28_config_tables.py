"""s28: CONFIG_SETTING and CONFIG_CHANGE (runtime configuration store and audit log).

Revision ID: 0003_config
Revises: 0002_group_role_mapping
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc

revision = "0003_config"
# s04's head; the merger re-points this if the spine merges in a different order.
down_revision = "0002_group_role_mapping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "config_setting",
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", JsonDoc(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(256), nullable=False),
        sa.PrimaryKeyConstraint("key", name="PK_CONFIG_SETTING"),
    )
    op.create_table(
        "config_change",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("old_value", JsonDoc(), nullable=True),
        sa.Column("new_value", JsonDoc(), nullable=False),
        sa.Column("changed_by", sa.String(256), nullable=False),
        sa.Column("changed_by_name", sa.String(256), nullable=False),
        sa.Column("changed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_CONFIG_CHANGE"),
    )
    op.create_index("IX_CONFIG_CHANGE_KEY_AT", "config_change", ["key", "changed_at"])


def downgrade() -> None:
    op.drop_index("IX_CONFIG_CHANGE_KEY_AT", table_name="config_change")
    op.drop_table("config_change")
    op.drop_table("config_setting")
