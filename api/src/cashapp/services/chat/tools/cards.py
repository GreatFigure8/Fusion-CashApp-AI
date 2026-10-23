"""Result cards a tool can attach to its ``tool_finished`` frame.

Defined in the business layer (tool modules build them, services must not import the API layer)
and re-exported by ``cashapp.api.schemas.chat``. ``kind`` discriminates the union.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from cashapp.domain.money import MoneyStr

__all__ = [
    "CardStat",
    "CardStatus",
    "ExportCard",
    "ReplayCard",
    "ReplayCurrency",
    "ResultCard",
    "StateCard",
    "TableCard",
    "TableColumn",
    "Tone",
]

Tone = Literal["ok", "accent", "warn", "err", "locked", "muted"]


class CardStat(BaseModel):
    label: str
    value: str


class CardStatus(BaseModel):
    label: str
    tone: Tone


class StateCard(BaseModel):
    kind: Literal["state_card"] = "state_card"
    title: str
    status: CardStatus
    stats: list[CardStat] = []
    history_id: str | None = None


class ReplayCurrency(BaseModel):
    currency: str
    newly_matched: MoneyStr
    newly_unmatched: MoneyStr
    items: int


class ReplayCard(BaseModel):
    kind: Literal["replay_card"] = "replay_card"
    candidate_id: str
    replay_id: str
    status: Literal["RUNNING", "DONE", "FAILED", "STALE"]
    changed: int
    newly_matched: int
    newly_failed: int
    newly_ambiguous: int
    currencies: list[ReplayCurrency] = []
    lab_href: str  # "/lab?candidate=p_0001&replay=rp_0001"


class ExportCard(BaseModel):
    kind: Literal["export_card"] = "export_card"
    filename: str
    size_bytes: int
    media_type: Literal["text/html"] = "text/html"
    self_contained: bool = True
    preview_href: str
    download_href: str


class TableColumn(BaseModel):
    key: str
    label: str
    numeric: bool = False


class TableCard(BaseModel):
    kind: Literal["table_card"] = "table_card"
    title: str
    columns: list[TableColumn]
    rows: list[dict[str, str | int | None]]
    total: int | None = None
    truncated: bool = False


ResultCard = Annotated[StateCard | ReplayCard | ExportCard | TableCard, Field(discriminator="kind")]
