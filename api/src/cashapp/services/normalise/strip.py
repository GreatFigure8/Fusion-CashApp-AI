"""Strip reply chains, signatures and disclaimers from an email body (text only)."""

import re

from cashapp.services.normalise.heuristics import AMOUNT

_WROTE = re.compile(r"^On .{1,200} wrote:$")
_WROTE_START = re.compile(r"^On .{1,200}$")
_WROTE_END = re.compile(r"^.{0,200} wrote:$")
_ORIGINAL = re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE)
_FORWARDED = re.compile(r"^(?:-{3,}\s*Forwarded message\s*-{3,}|Begin forwarded message:)", re.I)
_SIG_DELIMITER = re.compile(r"^-- ?$")
_DISCLAIMER = re.compile(
    r"^\W*(?:CONFIDENTIALITY NOTICE|DISCLAIMER|This e-?mail and any attachments"
    r"|This message (?:and any attachments )?is intended only"
    r"|Please consider the environment before printing)",
    re.IGNORECASE,
)
_SIGN_OFF = re.compile(
    r"^(?:best |kind |warm )?(?:regards|thanks|thank you|sincerely|cheers)\W*$", re.IGNORECASE
)
_HEADER_FIELD = re.compile(
    r"^\*?(From|Sent|Date|To|Cc|Bcc|Subject|Reply-To|Importance|Attachments):\*?\s*", re.I
)
_FROM = re.compile(r"^\*?From:\*?\s", re.IGNORECASE)
_SENT_OR_DATE = re.compile(r"^\*?(?:Sent|Date):\*?\s", re.IGNORECASE)
_TO_OR_SUBJECT = re.compile(r"^\*?(?:To|Subject):\*?\s", re.IGNORECASE)
_BLANKS = re.compile(r"\n{3,}")
_SIGN_OFF_MAX_LINES = 6
_SIGN_OFF_MAX_WIDTH = 60


def _is_wrote_start(lines: list[str], i: int) -> bool:
    stripped = lines[i].strip()
    if _WROTE.match(stripped):
        return True
    if _WROTE_START.match(stripped) and i + 1 < len(lines):
        following = lines[i + 1].strip()
        return bool(_WROTE_END.match(following)) and bool(_WROTE.match(f"{stripped} {following}"))
    return False


def _is_header_block(lines: list[str], i: int) -> bool:
    if not _FROM.match(lines[i].strip()):
        return False
    window = [line.strip() for line in lines[i + 1 : i + 5]]
    return any(_SENT_OR_DATE.match(w) for w in window) and any(
        _TO_OR_SUBJECT.match(w) for w in window
    )


def _skip_header_lines(lines: list[str], i: int) -> int:
    """Return the index of the first line after consecutive header-field lines from i."""
    while i < len(lines) and _HEADER_FIELD.match(lines[i].strip()):
        i += 1
    if i < len(lines) and not lines[i].strip():
        i += 1
    return i


def _cut_sign_off(kept: list[str]) -> list[str]:
    for idx in range(len(kept) - 1, -1, -1):
        trailing = [line.strip() for line in kept[idx + 1 :] if line.strip()]
        if len(trailing) > _SIGN_OFF_MAX_LINES:
            break
        if not _SIGN_OFF.match(kept[idx].strip()):
            continue
        if any(len(t) > _SIGN_OFF_MAX_WIDTH or AMOUNT.search(t) for t in trailing):
            continue
        return kept[:idx]
    return kept


def strip_body(text: str, *, is_forward: bool = False) -> str:
    """Return the body without reply chains, signatures and disclaimers.

    With `is_forward`, forwarded header blocks and markers are removed but the content
    below them is kept (the remittance is usually the forwarded content).
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith(">"):
            i += 1
            continue
        if _FORWARDED.match(stripped) and is_forward:
            i = _skip_header_lines(lines, i + 1)
            continue
        if _ORIGINAL.match(stripped):
            if not is_forward:
                break
            i = _skip_header_lines(lines, i + 1)
            continue
        if _is_header_block(lines, i):
            if not is_forward:
                break
            i = _skip_header_lines(lines, i)
            continue
        if _is_wrote_start(lines, i) or _SIG_DELIMITER.match(line) or _DISCLAIMER.match(stripped):
            break
        kept.append(line.rstrip())
        i += 1
    result = "\n".join(_cut_sign_off(kept))
    return _BLANKS.sub("\n\n", result).strip()
