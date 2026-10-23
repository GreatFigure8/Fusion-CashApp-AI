"""Does an (already stripped) email body look like it holds a remittance?"""

import re

_KEYWORD = re.compile(
    r"\b(?:inv(?:oice)?s?|credit\s+memos?|cm|bill|doc(?:ument)?)\b", re.IGNORECASE
)
_PREFIXED = re.compile(r"\b(?:inv|cm|dm)[-_ ]?\d{4,}", re.IGNORECASE)
_INVOICE_TOKEN = re.compile(r"[A-Za-z]{0,6}\d{4,}[A-Za-z0-9]*(?:-\d{1,2})?")
_SEPARATORS = re.compile(r"[\s,;:#()]+")
_LEAD = " \t#:.-"
AMOUNT = re.compile(r"(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d|\.\d)")
_FIELD_SPLIT = re.compile(r"\t| {2,}")


def _has_invoice_token(text: str) -> bool:
    if _PREFIXED.search(text):
        return True
    for keyword in _KEYWORD.finditer(text):
        tail = text[keyword.end() : keyword.end() + 80].lstrip(_LEAD)
        for token in _SEPARATORS.split(tail)[:3]:
            if _INVOICE_TOKEN.fullmatch(token.strip(".,")):
                return True
    return False


def _has_amount_table(text: str) -> bool:
    rows = 0
    for line in text.splitlines():
        if not AMOUNT.search(line):
            continue
        fields = [part for part in _FIELD_SPLIT.split(line.strip()) if part.strip()]
        if len(fields) >= 2:
            rows += 1
            if rows >= 2:
                return True
    return False


def body_looks_like_remittance(text: str) -> bool:
    """True with >= 1 invoice-like token or an amount table (>= 2 amount rows)."""
    return _has_invoice_token(text) or _has_amount_table(text)
