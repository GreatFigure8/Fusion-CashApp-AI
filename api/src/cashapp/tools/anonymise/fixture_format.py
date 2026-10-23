"""The pinned output format of the anonymised prior-build fixtures, and its loaders.

Everything under ``prior/`` is UTF-8 JSON with LF line endings, sorted keys, money as 2 dp strings
and ISO 8601 dates. Rows are sorted by ``message_id``. Extraction rows are the real
``RemittanceExtraction`` schema and outcome statuses are the shared status enums.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from pydantic import BaseModel

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import RemittanceExtraction
from cashapp.domain.money import MoneyStr
from cashapp.domain.stages import ItemState
from cashapp.domain.status import LineStatus, PaymentStatus

FORMAT_VERSION: Final = "1"
DEFAULT_PRIOR_DIR: Final[str] = "tests/fixtures/prior"  # relative to api/

MESSAGES_FILE: Final = "day/messages.jsonl"
FUSION_FILE: Final = "day/fusion.json"
FAILURES_FILE: Final = "labelled/failures.jsonl"
MANIFEST_FILE: Final = "manifest.json"
README_FILE: Final = "README.md"
MANAGED_FILES: Final[tuple[str, ...]] = (
    README_FILE,
    MANIFEST_FILE,
    MESSAGES_FILE,
    FUSION_FILE,
    FAILURES_FILE,
)


class PriorLabel(StrEnum):
    RECEIPT_IN_FUSION = "receipt_in_fusion"
    NOT_YET_ENTERED = "not_yet_entered"
    NOT_IN_FUSION = "not_in_fusion"
    FUTURE = "future"


class OutcomeLine(BaseModel, frozen=True):
    transaction_number: str
    line_status: LineStatus
    applied_amount: MoneyStr | None


class PriorOutcome(BaseModel, frozen=True):
    payment_status: PaymentStatus
    lines: list[OutcomeLine]
    receipt_number: str | None = None


class PriorMessage(BaseModel, frozen=True):
    """One line of ``prior/day/messages.jsonl``."""

    message_id: str
    extraction: RemittanceExtraction
    outcome: PriorOutcome


class LineLabel(BaseModel, frozen=True):
    transaction_number: str
    label: PriorLabel
    fusion_amount: MoneyStr | None


class PriorFailure(BaseModel, frozen=True):
    """One line of ``prior/labelled/failures.jsonl``."""

    message_id: str
    label: PriorLabel
    fusion_amount: MoneyStr | None
    line_labels: list[LineLabel]


class PriorManifest(BaseModel, frozen=True):
    format_version: str
    synthetic: bool
    seed: int | None
    key_id: str
    generated_by: str
    counts: dict[str, int]


class PriorFixtures(BaseModel, frozen=True):
    messages: list[PriorMessage]
    fusion: dict[str, Any]
    failures: list[PriorFailure]
    manifest: PriorManifest


# --- label -> expected auto-fix decision ----------------------------------------------------------


class ExpectedDecision(StrEnum):
    MATCHED = "matched"
    AWAITING_RECEIPT = "awaiting_receipt"
    ESCALATE_AFTER_AGING = "escalate_after_aging"


@dataclass(frozen=True)
class LabelExpectation:
    decision: ExpectedDecision
    item_state: ItemState  # state the item should reach first
    error_code: ErrorCode | None  # code the matcher raises (None when matched)
    terminal_state: ItemState  # state after aging, if it never matches
    terminal_error_code: ErrorCode | None


LABEL_EXPECTATIONS: Final[Mapping[PriorLabel, LabelExpectation]] = MappingProxyType(
    {
        PriorLabel.RECEIPT_IN_FUSION: LabelExpectation(
            ExpectedDecision.MATCHED, ItemState.PENDING, None, ItemState.DONE, None
        ),
        PriorLabel.NOT_YET_ENTERED: LabelExpectation(
            ExpectedDecision.AWAITING_RECEIPT,
            ItemState.AWAITING_RECEIPT,
            ErrorCode.RECEIPT_NOT_YET_AVAILABLE,
            ItemState.PENDING,  # woken by the receipt watcher
            None,
        ),
        PriorLabel.FUTURE: LabelExpectation(
            ExpectedDecision.AWAITING_RECEIPT,
            ItemState.AWAITING_RECEIPT,
            ErrorCode.RECEIPT_NOT_YET_AVAILABLE,
            ItemState.PENDING,  # woken by the receipt watcher
            None,
        ),
        PriorLabel.NOT_IN_FUSION: LabelExpectation(
            ExpectedDecision.ESCALATE_AFTER_AGING,
            ItemState.AWAITING_RECEIPT,
            ErrorCode.RECEIPT_NOT_YET_AVAILABLE,
            ItemState.ESCALATED,
            ErrorCode.AGED_OUT,
        ),
    }
)


def expected_for(label: PriorLabel) -> LabelExpectation:
    return LABEL_EXPECTATIONS[label]


# --- serialisation ------------------------------------------------------------


def dumps(value: Any) -> str:
    """Canonical JSON: sorted keys, UTF-8 text, no trailing newline."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def to_jsonl(rows: Iterable[BaseModel]) -> str:
    """One canonical JSON object per line, LF terminated."""
    return "".join(dumps(row.model_dump(mode="json")) + "\n" for row in rows)


def to_json_document(value: Any) -> str:
    return dumps(value) + "\n"


# --- loaders ------------------------------------------------------------


def _read_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_prior_day(prior_dir: Path) -> tuple[list[PriorMessage], dict[str, Any]]:
    """The day's messages and its ``fusion.json`` document (FusionScenario shape)."""
    messages = [
        PriorMessage.model_validate_json(line) for line in _read_lines(prior_dir / MESSAGES_FILE)
    ]
    fusion: dict[str, Any] = json.loads((prior_dir / FUSION_FILE).read_text(encoding="utf-8"))
    return messages, fusion


def load_labelled(prior_dir: Path) -> list[PriorFailure]:
    return [
        PriorFailure.model_validate_json(line) for line in _read_lines(prior_dir / FAILURES_FILE)
    ]


def load_manifest(prior_dir: Path) -> PriorManifest:
    return PriorManifest.model_validate_json((prior_dir / MANIFEST_FILE).read_text("utf-8"))
