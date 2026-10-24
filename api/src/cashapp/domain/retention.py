"""Retention purge vocabulary: what a purge touches, its pending/confirmed marker and its report."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from pydantic import JsonValue

RETENTION_AUDIT_KEY: Final = "retention.purge"
TOMBSTONE_ARTIFACT: Final = (
    "artifact purged under retention policy (content_hash={hash}, parts={parts}, bytes={bytes})"
)
TOMBSTONE_KIND: Final = "retention.artifact_purged"


class PurgeKind(StrEnum):
    ARTIFACT = "ARTIFACT"


class PurgeStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"


@dataclass(frozen=True, slots=True)
class PurgeReport:
    dry_run: bool
    ran_at: datetime
    artifacts: int  # items whose raw artifact was purged (or would be)
    parts: int  # ARTIFACT_PART rows purged
    readings: int  # EXTRACTION_READING rows nulled
    adjudications: int  # ADJUDICATION rows nulled
    history_payloads: int  # WORK_ITEM_HISTORY payloads nulled
    objects_deleted: int = 0
    objects_kept_shared: int = 0
    resumed: int = 0  # PENDING purges completed from an earlier crash
    skipped: int = 0  # candidates no longer eligible under lock, or purged concurrently
    lab_replay_items: int = 0  # LAB_REPLAY_ITEM rows of finished replays purged (or would be)

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "dry_run": self.dry_run,
            "ran_at": self.ran_at.isoformat(),
            "artifacts": self.artifacts,
            "parts": self.parts,
            "readings": self.readings,
            "adjudications": self.adjudications,
            "history_payloads": self.history_payloads,
            "objects_deleted": self.objects_deleted,
            "objects_kept_shared": self.objects_kept_shared,
            "resumed": self.resumed,
            "skipped": self.skipped,
            "lab_replay_items": self.lab_replay_items,
        }
