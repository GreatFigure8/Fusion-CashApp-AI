"""Admin-editable mapping from identity-domain group names to application roles."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Identity, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models import Base
from cashapp.domain.clock import utcnow
from cashapp.domain.principal import Role

_ROLE_VALUES = ", ".join(f"'{role.value}'" for role in Role)


class GroupRoleMapping(Base):
    __tablename__ = "GROUP_ROLE_MAPPING"
    __table_args__ = (
        UniqueConstraint("GROUP_NAME", "ROLE", name="UQ_GROUP_ROLE_MAPPING_GROUP_ROLE"),
        CheckConstraint(f"ROLE IN ({_ROLE_VALUES})", name="ROLE"),
    )

    id: Mapped[int] = mapped_column("ID", Identity(), primary_key=True)
    group_name: Mapped[str] = mapped_column("GROUP_NAME", String(256), nullable=False)
    role: Mapped[str] = mapped_column("ROLE", String(16), nullable=False)
    created_by: Mapped[str] = mapped_column("CREATED_BY", String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "CREATED_AT", DateTime(timezone=True), nullable=False, default=utcnow
    )
