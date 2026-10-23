"""group role mapping

Revision ID: 0002_group_role_mapping
Revises: 0001_base
Create Date: 2026-10-23 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cashapp.settings import get_settings

revision: str = "0002_group_role_mapping"
down_revision: str | None = "0001_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "GROUP_ROLE_MAPPING"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("ID", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("GROUP_NAME", sa.String(length=256), nullable=False),
        sa.Column("ROLE", sa.String(length=16), nullable=False),
        sa.Column("CREATED_BY", sa.String(length=256), nullable=False),
        sa.Column(
            "CREATED_AT",
            sa.DateTime(timezone=True),
            server_default=sa.text("SYSTIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("ID", name="PK_GROUP_ROLE_MAPPING"),
        sa.UniqueConstraint("GROUP_NAME", "ROLE", name="UQ_GROUP_ROLE_MAPPING_GROUP_ROLE"),
        sa.CheckConstraint(
            "ROLE IN ('ADMIN', 'OPERATOR', 'REVERSER', 'VIEWER')",
            name="CK_GROUP_ROLE_MAPPING_ROLE",
        ),
    )
    bootstrap_group = get_settings().identity.bootstrap_admin_group
    op.execute(
        sa.text(
            "INSERT INTO GROUP_ROLE_MAPPING (GROUP_NAME, ROLE, CREATED_BY) "
            "VALUES (:group_name, 'ADMIN', 'system:bootstrap')"
        ).bindparams(group_name=bootstrap_group)
    )


def downgrade() -> None:
    op.drop_table(TABLE)
