"""The trailing action block: hold it back from the stream, then parse it fail-closed.

The model ends a reply with ``<<<actions [...] >>>``. ``ActionBlockSplitter`` keeps that block
(and any suffix that could still turn into its opening marker) out of the emitted text.
``parse_action_block`` keeps only ids the caller allowed, dedupes, caps and clamps.
"""

import json
import logging
from collections.abc import Collection
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, ValidationError

from cashapp.services.chat.events import ActionEvent
from cashapp.services.chat.prompts import ACTION_BLOCK_CLOSE, ACTION_BLOCK_OPEN

logger = logging.getLogger(__name__)

MAX_ACTIONS: Final = 3
LABEL_MAX: Final = 80


class _RawAction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: StrictStr
    label: StrictStr | None = None
    args: dict[str, StrictStr | StrictInt | StrictBool | None] = {}


class ActionBlockSplitter:
    """Streaming split of reply text into safe text and the trailing action block."""

    def __init__(self) -> None:
        self._pending = ""  # text that might still become the opening marker
        self._block: str | None = None  # everything from the marker on, once seen

    def feed(self, delta: str) -> str:
        """The part of ``delta`` (plus earlier held-back text) that is safe to show."""
        if self._block is not None:
            self._block += delta
            return ""
        text = self._pending + delta
        index = text.find(ACTION_BLOCK_OPEN)
        if index >= 0:
            self._block = text[index:]
            self._pending = ""
            return text[:index]
        hold = _partial_marker_length(text)
        self._pending = text[len(text) - hold :] if hold else ""
        return text[: len(text) - hold]

    def finish(self) -> tuple[str, str | None]:
        """The remaining safe text (a held-back partial marker is real text) and the raw block."""
        if self._block is not None:
            return "", self._block
        rest, self._pending = self._pending, ""
        return rest, None


def _partial_marker_length(text: str) -> int:
    """Length of the longest suffix of ``text`` that is a proper prefix of the marker."""
    longest = min(len(text), len(ACTION_BLOCK_OPEN) - 1)
    for size in range(longest, 0, -1):
        if text.endswith(ACTION_BLOCK_OPEN[:size]):
            return size
    return 0


def _block_payload(raw: str) -> str | None:
    body = raw[len(ACTION_BLOCK_OPEN) :] if raw.startswith(ACTION_BLOCK_OPEN) else raw
    end = body.find(ACTION_BLOCK_CLOSE)
    if end < 0:
        return None
    return body[:end].strip()


def parse_action_block(
    raw: str | None, allowed: Collection[str], *, limit: int = MAX_ACTIONS
) -> list[ActionEvent]:
    """Actions the model proposed that are in ``allowed``; anything malformed yields none.

    Text after the closing marker is ignored. Only the block's length is ever logged.
    """
    if raw is None:
        return []
    payload = _block_payload(raw)
    if payload is None:
        logger.warning("Dropped an unterminated action block", extra={"block_chars": len(raw)})
        return []
    try:
        decoded = json.loads(payload)
    except ValueError:
        decoded = None
    if not isinstance(decoded, list):
        logger.warning("Dropped an unparsable action block", extra={"block_chars": len(raw)})
        return []
    events: list[ActionEvent] = []
    seen: set[str] = set()
    for entry in cast("list[Any]", decoded):
        try:
            item = _RawAction.model_validate(entry)
        except ValidationError:
            continue  # nested or non-scalar args, or no id: this action only
        if item.id not in allowed or item.id in seen:
            continue
        seen.add(item.id)
        label = (item.label or "").strip() or item.id
        events.append(ActionEvent(id=item.id, label=label[:LABEL_MAX], args=dict(item.args)))
        if len(events) >= limit:
            break
    return events
