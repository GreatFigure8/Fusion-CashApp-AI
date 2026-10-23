"""RFC 822 email (.eml) and the shared email assembly also used by .msg."""

import mimetypes
import re
from dataclasses import dataclass, field
from email import policy
from email.message import MIMEPart
from email.parser import BytesParser

from cashapp.domain.artifacts import UnsupportedReason
from cashapp.services.normalise.formats.text import decode_text, html_to_text
from cashapp.services.normalise.model import (
    EmailNode,
    Item,
    Node,
    WalkContext,
    unique_name,
)
from cashapp.services.normalise.sniff import EML, MSG
from cashapp.services.normalise.strip import strip_body

_FORWARD_SUBJECT = re.compile(r"^\s*(?:fw|fwd):", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class AttachmentInput:
    """One attachment: raw bytes to sniff, or an already-parsed nested message."""

    filename: str
    data: bytes | None = None
    content_type: str | None = None
    content_id: str | None = None
    nested: "EmailInput | None" = None


@dataclass(frozen=True, slots=True)
class EmailInput:
    """Format-neutral view of a message, produced by the eml and msg readers."""

    sender: str
    subject: str
    date: str
    body_text: str
    body_html: str
    attachments: list[AttachmentInput] = field(default_factory=list[AttachmentInput])


def _header_lines(email: EmailInput) -> str:
    return "\n".join([f"From: {email.sender}", f"Subject: {email.subject}", f"Date: {email.date}"])


def _is_decoration(att: AttachmentInput, html: str, min_bytes: int) -> bool:
    if not att.content_id or att.data is None or len(att.data) >= min_bytes:
        return False
    if not (att.content_type or "").startswith("image/"):
        return False
    return f"cid:{att.content_id}".lower() in html.lower()


def build_email_node(
    email: EmailInput, path: str, media_type: str, depth: int, ctx: WalkContext
) -> EmailNode:
    """Strip the body, walk every attachment, and return the email sub-tree."""
    body = email.body_text if email.body_text.strip() else html_to_text(email.body_html)
    stripped = strip_body(body, is_forward=bool(_FORWARD_SUBJECT.match(email.subject)))
    children: list[Node] = []
    seen: set[str] = set()
    for att in email.attachments:
        att_path = f"{path}/attachments/{unique_name(att.filename, seen)}"
        if _is_decoration(att, email.body_html, ctx.limits.min_inline_image_bytes):
            ctx.note(
                att_path,
                att.content_type or "",
                UnsupportedReason.UNKNOWN_FORMAT,
                "inline decoration",
            )
            continue
        if att.nested is not None:
            nested = att.nested
            child = ctx.guarded(
                att_path,
                MSG,
                lambda nested=nested, att_path=att_path: _nested(nested, att_path, depth + 1, ctx),
            )
        else:
            child = ctx.walk_child(
                att.data or b"", att.filename, att.content_type, att_path, depth + 1
            )
        if child is not None:
            children.append(child)
    text = f"{_header_lines(email)}\n\n{stripped}" if stripped else ""
    return EmailNode(path=path, stripped=stripped, text=text, children=children)


def _nested(email: EmailInput, path: str, depth: int, ctx: WalkContext) -> Node:
    ctx.check_depth(depth)
    return build_email_node(email, path, MSG, depth, ctx)


def _part_text(part: MIMEPart) -> str:
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
    except (LookupError, UnicodeDecodeError, ValueError, KeyError):
        pass
    payload = part.get_payload(decode=True)
    return decode_text(payload) if isinstance(payload, bytes) else ""


def _leaves(part: MIMEPart) -> list[MIMEPart]:
    if part.get_content_type() == "message/rfc822" or not part.is_multipart():
        return [part]
    return [leaf for sub in part.iter_parts() for leaf in _leaves(sub)]


def _attachment(part: MIMEPart, index: int) -> AttachmentInput:
    content_type = part.get_content_type()
    filename = part.get_filename()
    cid = str(part.get("Content-ID") or "").strip("<> ") or None
    if content_type == "message/rfc822":
        inner = next(part.iter_parts(), None)
        data = inner.as_bytes() if inner is not None else b""
        return AttachmentInput(filename or f"attached-message-{index}.eml", data, EML, cid)
    payload = part.get_payload(decode=True)
    data = payload if isinstance(payload, bytes) else b""
    extension = mimetypes.guess_extension(content_type) or ""
    return AttachmentInput(filename or f"part-{index}{extension}", data, content_type, cid)


def _email_input(message: MIMEPart) -> EmailInput:
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    body_parts = [p for p in (plain, html) if p is not None]
    attachments: list[AttachmentInput] = []
    for index, part in enumerate(_leaves(message), start=1):
        is_attachment = bool(part.get_filename()) or part.get_content_disposition() == "attachment"
        if not is_attachment and any(part is body for body in body_parts):
            continue
        attachments.append(_attachment(part, index))
    return EmailInput(
        sender=str(message["From"] or ""),
        subject=str(message["Subject"] or ""),
        date=str(message["Date"] or ""),
        body_text=_part_text(plain) if plain is not None else "",
        body_html=_part_text(html) if html is not None else "",
        attachments=attachments,
    )


def handle_eml(item: Item, ctx: WalkContext) -> EmailNode:
    parsed = BytesParser(policy=policy.default).parsebytes(item.data)
    return build_email_node(_email_input(parsed), item.path, item.media_type, item.depth, ctx)
