"""REPORT_EXPORT: a log of the HTML progress reports people exported. The HTML is not stored."""

from datetime import datetime

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.reports import HtmlReportKind


class ReportExport(Base):
    __tablename__ = "report_export"
    __table_args__ = (Index("IX_REPORT_EXPORT_AT", "at"),)

    id: Mapped[int] = identity_pk()
    kind: Mapped[HtmlReportKind] = mapped_column(StrEnumType(HtmlReportKind), nullable=False)
    window: Mapped[str] = mapped_column(String(8), nullable=False)
    # Section names, in document order. No remittance content is ever stored here.
    sections: Mapped[list[str]] = mapped_column(JsonDoc(), nullable=False)
    filename: Mapped[str] = mapped_column(String(120), nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # The principal's subject and display name.
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
