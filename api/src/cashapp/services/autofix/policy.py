"""Policy guards: remittances a person must always decide, found in code and not by a model.

``policy_check`` is called by validate (s10) and receipt matching (s13). The heuristics are a
starting point: a line with no evidence to check against is reported as unchecked, never as a
pass and never as a failure. Callers raise ``StageError(code, detail=findings.detail())``; the
detail holds line numbers only, no text.
"""

import re
from dataclasses import dataclass
from typing import Any, Final

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import ExtractedLine, LineKind, RemittanceExtraction

PREPAYMENT_MARKERS: Final[re.Pattern[str]] = re.compile(
    r"pre-?pay|advance\s+payment|on[\s-]account|deposit", re.IGNORECASE
)

_NUMBER_LINES: Final = frozenset({LineKind.INVOICE, LineKind.CREDIT_MEMO, LineKind.UNKNOWN})
_NON_ALNUM: Final = re.compile(r"[^A-Za-z0-9]")


@dataclass(frozen=True, slots=True)
class PolicyFindings:
    code: ErrorCode | None
    ungrounded_lines: tuple[int, ...] = ()
    unchecked_lines: tuple[int, ...] = ()

    def detail(self) -> dict[str, Any]:
        return {
            "ungrounded_lines": list(self.ungrounded_lines),
            "unchecked_lines": list(self.unchecked_lines),
        }


def _normalise(text: str) -> str:
    return _NON_ALNUM.sub("", text).upper()


def _bears_number(line: ExtractedLine) -> bool:
    return line.kind in _NUMBER_LINES and bool(line.transaction_number.strip())


def _quotes(extraction: RemittanceExtraction) -> list[str]:
    found: list[str] = []
    for _, field in extraction.iter_fields():
        source = field.source
        if source is not None and source.quote:
            found.append(source.quote)
    return found


def _has_prepayment_marker(extraction: RemittanceExtraction) -> bool:
    texts = [extraction.notes or "", extraction.remittance_reference.value or ""]
    texts.extend(_quotes(extraction))
    return any(PREPAYMENT_MARKERS.search(text) for text in texts if text)


def _has_other_references(extraction: RemittanceExtraction) -> bool:
    if extraction.po_refs or extraction.sales_order_refs or extraction.ers_refs:
        return True
    return any(
        line.po_number or line.sales_order or line.ers_reference for line in extraction.lines
    )


def _grounding(
    lines: list[ExtractedLine], artifact_text: str | None
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    haystack = _normalise(artifact_text) if artifact_text else None
    ungrounded: list[int] = []
    unchecked: list[int] = []
    for line in lines:
        number = _normalise(line.transaction_number)
        quote = line.source.quote if line.source is not None else None
        evidence = _normalise(quote) if quote else haystack
        if evidence is None:
            unchecked.append(line.line_no)
        elif number not in evidence:
            ungrounded.append(line.line_no)
    return tuple(ungrounded), tuple(unchecked)


def policy_findings(
    extraction: RemittanceExtraction, *, artifact_text: str | None = None
) -> PolicyFindings:
    """Precedence: PREPAYMENT, then PO_SO_ERS_ONLY, then UNGROUNDED."""
    numbered = [line for line in extraction.lines if _bears_number(line)]
    if not numbered:
        if _has_prepayment_marker(extraction):
            return PolicyFindings(code=ErrorCode.PREPAYMENT)
        if _has_other_references(extraction):
            return PolicyFindings(code=ErrorCode.PO_SO_ERS_ONLY)
        return PolicyFindings(code=None)
    ungrounded, unchecked = _grounding(numbered, artifact_text)
    return PolicyFindings(
        code=ErrorCode.UNGROUNDED if ungrounded else None,
        ungrounded_lines=ungrounded,
        unchecked_lines=unchecked,
    )


def policy_check(
    extraction: RemittanceExtraction, *, artifact_text: str | None = None
) -> ErrorCode | None:
    return policy_findings(extraction, artifact_text=artifact_text).code
