"""REPORT_RUN: one stored report per kind and day, with who generated and emailed it."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.reports import ReportKind


class ReportRun(Base):
    __tablename__ = "report_run"
    __table_args__ = (UniqueConstraint("kind", "report_date", name="UQ_REPORT_RUN_KIND_DATE"),)

    id: Mapped[int] = identity_pk()
    kind: Mapped[ReportKind] = mapped_column(StrEnumType(ReportKind), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    # "first-event-after-cutover" or "user:<subject>"
    generated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    generated_by_name: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDoc(), nullable=False)
    emailed_to: Mapped[list[str] | None] = mapped_column(JsonDoc(), nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
