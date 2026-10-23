"""s48: APP_SECRET, secrets stored encrypted in the database.

Revision ID: s48_app_secret
Revises: s48_lab_replay
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import UtcDateTime

revision = "s48_app_secret"
down_revision = "s48_lab_replay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_secret",
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.Column("updated_by", sa.String(256), nullable=False),
        sa.PrimaryKeyConstraint("name", name="PK_APP_SECRET"),
    )


def downgrade() -> None:
    op.drop_table("app_secret")
