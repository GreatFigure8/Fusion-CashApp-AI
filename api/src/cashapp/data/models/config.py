"""ORM models for the runtime configuration store and its change log."""

from datetime import datetime
from typing import Any

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, UtcDateTime, identity_pk


class ConfigSetting(Base):
    """One stored override of a registry key. A missing row means "registry default"."""

    __tablename__ = "config_setting"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JsonDoc, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(256), nullable=False)


class ConfigChange(Base):
    """Append-only audit row: who changed which key, when, from what to what, and why."""

    __tablename__ = "config_change"
    __table_args__ = (Index("IX_CONFIG_CHANGE_KEY_AT", "key", "changed_at"),)

    id: Mapped[int] = identity_pk()
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[Any] = mapped_column(JsonDoc, nullable=True)
    new_value: Mapped[Any] = mapped_column(JsonDoc, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(256), nullable=False)
    changed_by_name: Mapped[str] = mapped_column(String(256), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    # One promote of several keys shares a change set; lab ids carry no FK so config history
    # never depends on lab rows.
    change_set_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lab_candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lab_replay_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
