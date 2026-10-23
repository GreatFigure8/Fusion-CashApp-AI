"""Typed Fusion errors: every failure maps to an auto-fix `ErrorCode`."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.models import FusionMessage

NOISE_CODES: frozenset[str] = frozenset(
    {
        "AR_RAPI_TRX_NUM_IGN",
        "AR_RAPI_RCPT_NUM_IGN",
        "GENERIC_MESSAGE",
        "FND_AS_UNEXPECTED_ERROR",
        "AR-855741",
        "AR-855799",
    }
)

FUSION_CODE_MAP: Mapping[str, ErrorCode] = MappingProxyType(
    {
        "AR-855287": ErrorCode.FUSION_OVERAPPLY,
        "AR-856102": ErrorCode.FUSION_ALREADY_APPLIED,
        "ORA-00054": ErrorCode.FUSION_LOCKED,
        "AR-856792": ErrorCode.FUSION_LOCKED,
        "AR-856089": ErrorCode.FUSION_GL_DATE,
    }
)

# Precedence when several real faults arrive together.
_PRECEDENCE: tuple[ErrorCode, ...] = (
    ErrorCode.FUSION_OVERAPPLY,
    ErrorCode.FUSION_ALREADY_APPLIED,
    ErrorCode.FUSION_GL_DATE,
    ErrorCode.FUSION_LOCKED,
)

_MAX_MESSAGE = 300
_NOT_AUTHORIZED = re.compile(rb"NotAuthorizedOrNotFound", re.IGNORECASE)


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX_MESSAGE else text[:_MAX_MESSAGE] + "..."


@dataclass(frozen=True, slots=True)
class FusionFault:
    code: ErrorCode
    fusion_code: str | None
    message: str
    messages: tuple[FusionMessage, ...]


class FusionError(Exception):
    """A Fusion failure the caller must handle (transport, guard, parse, or fault)."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        fusion_code: str | None = None,
        retryable: bool | None = None,
        http_status: int | None = None,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fusion_code = fusion_code
        self.retryable = code.spec.retryable if retryable is None else retryable
        self.http_status = http_status
        self.outcome_unknown = outcome_unknown

    @classmethod
    def from_fault(cls, fault: FusionFault) -> FusionError:
        return cls(fault.code, fault.message, fusion_code=fault.fusion_code)

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"


def classify_fusion_code(fusion_code: str | None) -> ErrorCode:
    if fusion_code is None:
        return ErrorCode.FUSION_FAULT
    return FUSION_CODE_MAP.get(fusion_code.upper(), ErrorCode.FUSION_FAULT)


def is_noise(message: FusionMessage) -> bool:
    return (message.code or "").upper() in NOISE_CODES


def fault_from_messages(messages: Sequence[FusionMessage]) -> FusionFault | None:
    """Drop noise; return the highest-precedence real fault, or None if nothing real is left."""
    real = tuple(m for m in messages if not is_noise(m))
    if not real:
        return None
    chosen = real[0]
    for code in _PRECEDENCE:
        match = next((m for m in real if classify_fusion_code(m.code) is code), None)
        if match is not None:
            chosen = match
            break
    return FusionFault(
        code=classify_fusion_code(chosen.code),
        fusion_code=chosen.code,
        message=_clip(chosen.text) or (chosen.code or "Fusion fault"),
        messages=real,
    )


def error_from_http(status: int, body: bytes | None) -> FusionError:
    """Map an HTTP failure to a typed error. The body is inspected, never echoed."""
    if status == 401 or status >= 500:
        return FusionError(
            ErrorCode.FUSION_TRANSIENT, f"HTTP {status} from Fusion", http_status=status
        )
    if status == 404 and body is not None and _NOT_AUTHORIZED.search(body):
        return FusionError(
            ErrorCode.FUSION_TRANSIENT,
            "HTTP 404 NotAuthorizedOrNotFound from Fusion",
            http_status=status,
        )
    return FusionError(
        ErrorCode.FUSION_FAULT, f"HTTP {status} from Fusion", http_status=status, retryable=False
    )
