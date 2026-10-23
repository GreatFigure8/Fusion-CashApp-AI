"""Builds the PII-free message for a batch of events.

Bodies carry item ids, error codes, counts and links only. An event's free-text summary is shown
only for the kinds whose summaries this package builds itself from stage names and counts.
"""

import html
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from cashapp.domain.notifications import NotifyEvent, NotifyKind

SYSTEM_SUMMARY_KINDS: Final = frozenset({NotifyKind.DLQ_GROWTH.value, NotifyKind.OUTAGE.value})
MAX_LISTED_ITEMS: Final = 200
SUBJECT_MAX: Final = 400


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    subject: str
    body_text: str
    body_html: str
    item_ids: tuple[int, ...]


def _minutes(window_seconds: int) -> int:
    return max(1, round(window_seconds / 60))


def _subject(kind: str, events: Sequence[NotifyEvent], window_seconds: int, env_label: str) -> str:
    count = len(events)
    if kind == NotifyKind.ITEM_ESCALATED.value:
        noun = "item" if count == 1 else "items"
        verb = "escalated"
        text = f"{count} {noun} {verb} in the last {_minutes(window_seconds)} minutes"
    elif kind == NotifyKind.DLQ_GROWTH.value:
        text = "Dead-letter queue grew"
    elif kind == NotifyKind.OUTAGE.value:
        codes = sorted({e.error_code.value for e in events if e.error_code is not None})
        text = f"Possible outage: {', '.join(codes) if codes else 'unknown'} errors"
    elif kind == NotifyKind.BUDGET_EXCEEDED.value:
        text = "Daily LLM budget exceeded"
    else:
        text = f"{count} {kind} events"
    return f"[CashApp {env_label}] {text}"[:SUBJECT_MAX]


def _link(item_id: int, app_base_url: str | None) -> str:
    path = f"/exceptions?item={item_id}"
    if app_base_url:
        return f"{app_base_url.rstrip('/')}{path}"
    return path


def _event_line(event: NotifyEvent, kind: str, app_base_url: str | None) -> str:
    parts: list[str] = []
    if event.work_item_id is not None:
        parts.append(f"item {event.work_item_id}")
    if event.error_code is not None:
        parts.append(event.error_code.value)
    parts.append(event.occurred_at.isoformat())
    if event.work_item_id is not None:
        parts.append(_link(event.work_item_id, app_base_url))
    if kind in SYSTEM_SUMMARY_KINDS:
        parts.append(event.summary)
    return "  ".join(parts)


def render_batch(
    kind: str,
    events: Sequence[NotifyEvent],
    *,
    window_seconds: int,
    env_label: str,
    app_base_url: str | None,
) -> RenderedMessage:
    ordered = sorted(events, key=lambda e: e.occurred_at)
    subject = _subject(kind, ordered, window_seconds, env_label)
    listed = ordered[:MAX_LISTED_ITEMS]
    lines = [_event_line(event, kind, app_base_url) for event in listed]
    hidden = len(ordered) - len(listed)
    if hidden > 0:
        lines.append(f"and {hidden} more")
    header = f"{len(ordered)} event(s) of kind {kind} in the last {_minutes(window_seconds)} min."
    body_text = "\n".join([header, "", *lines])
    html_lines = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
    body_html = f"<p>{html.escape(header)}</p><ul>{html_lines}</ul>"
    item_ids = tuple(sorted({e.work_item_id for e in ordered if e.work_item_id is not None}))
    return RenderedMessage(subject, body_text, body_html, item_ids)
