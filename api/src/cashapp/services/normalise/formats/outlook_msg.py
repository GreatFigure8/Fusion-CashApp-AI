"""Outlook .msg via extract-msg, confined to this module behind a typed seam."""

import io
from dataclasses import dataclass, field
from typing import Any, cast

from cashapp.services.normalise.formats.mime_email import (
    AttachmentInput,
    EmailInput,
    build_email_node,
)
from cashapp.services.normalise.model import EmailNode, Item, WalkContext


@dataclass(frozen=True, slots=True)
class MsgAttachment:
    filename: str
    data: bytes | None = None
    nested: "MsgContent | None" = None
    content_id: str | None = None
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class MsgContent:
    sender: str
    subject: str
    date: str
    body_text: str
    body_html: str
    attachments: list[MsgAttachment] = field(default_factory=list[MsgAttachment])


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


def _convert(message: Any) -> MsgContent:
    attachments: list[MsgAttachment] = []
    for index, att in enumerate(message.attachments, start=1):
        name = _text(att.longFilename) or _text(att.shortFilename) or _text(att.name)
        cid = _text(att.cid) or None
        mimetype = _text(att.mimetype) or None
        payload = att.data
        if isinstance(payload, bytes):
            attachments.append(
                MsgAttachment(name or f"attachment-{index}", payload, None, cid, mimetype)
            )
        elif payload is not None and hasattr(payload, "attachments"):
            attachments.append(
                MsgAttachment(name or f"attached-message-{index}.msg", None, _convert(payload))
            )
    return MsgContent(
        sender=_text(message.sender),
        subject=_text(message.subject),
        date=_text(message.date),
        body_text=_text(message.body),
        body_html=_text(message.htmlBody),
        attachments=attachments,
    )


def open_msg(data: bytes) -> MsgContent:
    """Parse .msg bytes into typed local dataclasses (the only extract-msg call site)."""
    import extract_msg

    message = cast(Any, extract_msg).openMsg(io.BytesIO(data))
    try:
        return _convert(message)
    finally:
        message.close()


def _to_input(content: MsgContent) -> EmailInput:
    return EmailInput(
        sender=content.sender,
        subject=content.subject,
        date=content.date,
        body_text=content.body_text,
        body_html=content.body_html,
        attachments=[
            AttachmentInput(
                filename=a.filename,
                data=a.data,
                content_type=a.content_type,
                content_id=a.content_id,
                nested=_to_input(a.nested) if a.nested is not None else None,
            )
            for a in content.attachments
        ],
    )


def handle_msg(item: Item, ctx: WalkContext) -> EmailNode:
    return build_email_node(
        _to_input(open_msg(item.data)), item.path, item.media_type, item.depth, ctx
    )
