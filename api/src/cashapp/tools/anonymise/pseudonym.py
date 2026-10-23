"""Keyed, deterministic pseudonyms.

``digest(kind, value) = HMAC-SHA256(key, kind + NUL + normalise(value))``. Codes are assigned in
two passes: ``register`` every value in the bundle, then ``freeze``. A code that two distinct
values would share is lengthened for both (never an error, never order-dependent), so the output
depends on the set of values and the key only, not on file or row order.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Final

from cashapp.tools.anonymise.scan import EMAIL_PATTERN

EMAIL_PLACEHOLDER: Final = "[email]"
NUMBER_PLACEHOLDER: Final = "[number]"

GENERIC_TERMS: Final = re.compile(
    r"^(?:IMMEDIATE|NET\s*\d{1,3}|\d{1,2}\s*%\s*\d{1,3}\s*NET\s*\d{1,3})$", re.IGNORECASE
)
_SUFFIX: Final = re.compile(r"-\d{1,2}$")
_SPLIT_MESSAGE: Final = re.compile(r"^(?P<base>.*)#(?P<n>\d+)$", re.DOTALL)
_MIN_SCRUB_LENGTH: Final = 3
_B32_CAP: Final = 52
_DIGIT_CAP: Final = 70
_STEP: Final = 2
_ACCOUNT_LENGTHS: Final = ((6, 6), (9, 8))  # (max source length, output length)
_ACCOUNT_LONG: Final = 10


class PseudonymError(Exception):
    """A value was not registered before ``freeze``, or codes cannot be made unique."""


class Kind(StrEnum):
    CUSTOMER_NAME = "customer_name"
    ACCOUNT = "account"
    INVOICE = "invoice"
    RECEIPT = "receipt"
    REFERENCE = "reference"
    PURCHASE_ORDER = "po"
    SALES_ORDER = "so"
    ERS = "ers"
    MESSAGE = "message"
    BANK = "bank"
    BUSINESS_UNIT = "business_unit"
    SITE = "site"
    TERMS = "terms"


@dataclass(frozen=True)
class _Spec:
    prefix: str
    alphabet: str  # "digits" or "base32"
    length: int
    suffix: bool = False
    casefold: bool = False


_SPECS: Final[dict[Kind, _Spec]] = {
    Kind.CUSTOMER_NAME: _Spec("Customer-", "base32", 4, casefold=True),
    Kind.ACCOUNT: _Spec("9", "digits", 0),
    Kind.INVOICE: _Spec("INV-", "digits", 8, suffix=True),
    Kind.RECEIPT: _Spec("RCPT-", "digits", 8, suffix=True),
    Kind.REFERENCE: _Spec("REF-", "digits", 8),
    Kind.PURCHASE_ORDER: _Spec("PO-", "digits", 8),
    Kind.SALES_ORDER: _Spec("SO-", "digits", 8),
    Kind.ERS: _Spec("ERS-", "digits", 8),
    Kind.MESSAGE: _Spec("MSG-", "digits", 8),
    Kind.BANK: _Spec("BANK-", "digits", 8),
    Kind.BUSINESS_UNIT: _Spec("BU-", "base32", 2),
    Kind.SITE: _Spec("SITE-", "base32", 4),
    Kind.TERMS: _Spec("TERMS-", "base32", 2),
}


def normalise(kind: Kind, value: str) -> str:
    """NFKC, collapsed whitespace; names are also casefolded."""
    text = " ".join(unicodedata.normalize("NFKC", value).split())
    return text.casefold() if _SPECS[kind].casefold else text


def _account_length(value: str) -> int:
    for limit, out in _ACCOUNT_LENGTHS:
        if len(value) <= limit:
            return out
    return _ACCOUNT_LONG


def _split_suffix(kind: Kind, value: str) -> tuple[str, str]:
    """Split a trailing ``-n`` (invoices, receipts) so ``X`` and ``X-1`` share a base."""
    if _SPECS[kind].suffix:
        match = _SUFFIX.search(value)
        if match is not None and match.start() > 0:
            return value[: match.start()], match.group(0)
    return value, ""


def _split_message(value: str) -> tuple[str, str]:
    match = _SPLIT_MESSAGE.match(value)
    if match is None:
        return value, ""
    return match.group("base"), f"-P{match.group('n')}"


def _split(kind: Kind, value: str) -> tuple[str, str]:
    if kind is Kind.MESSAGE:
        return _split_message(value)
    return _split_suffix(kind, value)


class Pseudonymiser:
    def __init__(self, key: bytes) -> None:
        self._key = key
        self._registered: dict[Kind, set[str]] = {kind: set() for kind in Kind}
        self._vocab: dict[Kind, dict[str, str]] = {}
        self._scrub: re.Pattern[str] | None = None
        self._scrub_lookup: dict[str, tuple[Kind, str]] = {}
        self._frozen = False
        self._offset = timedelta(days=-7 * (35 + self.digest_int("date-offset", "") % 52))

    # --- digests ---------------------------------------------------------------------------------

    def _digest_bytes(self, kind: str, value: str) -> bytes:
        message = f"{kind}\x00{value}".encode()
        return hmac.new(self._key, message, hashlib.sha256).digest()

    def digest_int(self, kind: str, value: str) -> int:
        return int.from_bytes(self._digest_bytes(kind, value), "big")

    # --- registration ----------------------------------------------------------------------------

    def register(self, kind: Kind, value: str | None) -> None:
        """Record a source value; call for every value before ``freeze``."""
        if self._frozen:
            raise PseudonymError("register after freeze")
        if value is None or not value.strip():
            return
        if kind is Kind.TERMS and GENERIC_TERMS.match(value.strip()):
            return
        base, _suffix = _split(kind, normalise(kind, value))
        if base:
            self._registered[kind].add(base)

    def register_many(self, kind: Kind, values: Iterable[str | None]) -> None:
        for value in values:
            self.register(kind, value)

    def freeze(self) -> None:
        """Assign every code and prepare the free-text scrubber."""
        self._vocab = {kind: self._assign(kind, keys) for kind, keys in self._registered.items()}
        self._frozen = True
        self._build_scrubber()

    def _code(self, kind: Kind, key: str, step: int) -> str:
        spec = _SPECS[kind]
        base_length = _account_length(key) if kind is Kind.ACCOUNT else spec.length
        length = base_length + step * _STEP
        digest = self._digest_bytes(kind.value, key)
        if spec.alphabet == "base32":
            if length > _B32_CAP:
                raise PseudonymError("pseudonym collision cannot be resolved")
            return base64.b32encode(digest).decode("ascii")[:length]
        digits = length - len(spec.prefix) if kind is Kind.ACCOUNT else length
        if digits > _DIGIT_CAP:
            raise PseudonymError("pseudonym collision cannot be resolved")
        number = int.from_bytes(digest, "big") % 10**digits
        return str(number).zfill(digits)

    def _assign(self, kind: Kind, keys: set[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        taken: set[str] = set()
        pending: list[str] = sorted(keys)
        step = 0
        while pending:
            groups: dict[str, list[str]] = {}
            for key in pending:
                groups.setdefault(self._code(kind, key, step), []).append(key)
            pending = []
            for code in sorted(groups):
                members = groups[code]
                if len(members) == 1 and code not in taken:
                    result[members[0]] = code
                    taken.add(code)
                else:
                    pending.extend(members)
            step += 1
        return result

    # --- lookup ----------------------------------------------------------------------------------

    def map(self, kind: Kind, value: str) -> str:
        """Pseudonym for a registered value, with any ``-n`` suffix (or ``#n``) preserved."""
        if not self._frozen:
            raise PseudonymError("map before freeze")
        spec = _SPECS[kind]
        if kind is Kind.TERMS and GENERIC_TERMS.match(value.strip()):
            return " ".join(value.split()).upper()
        base, suffix = _split(kind, normalise(kind, value))
        code = self._vocab[kind].get(base)
        if code is None:
            raise PseudonymError(f"unregistered {kind.value} value")
        return f"{spec.prefix}{code}{suffix}"

    def map_optional(self, kind: Kind, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return self.map(kind, value)

    # --- dates -----------------------------------------------------------------------------------

    @property
    def date_offset(self) -> timedelta:
        return self._offset

    def shift_date(self, value: date) -> date:
        return value + self._offset

    def shift_datetime(self, value: datetime) -> datetime:
        return value + self._offset

    # --- free text -------------------------------------------------------------------------------

    def _build_scrubber(self) -> None:
        pieces: list[str] = []
        lookup: dict[str, tuple[Kind, str]] = {}
        for kind in Kind:  # fixed order: the first kind to claim a text wins
            for key in self._vocab[kind]:
                text = key.casefold()
                if len(text) >= _MIN_SCRUB_LENGTH and text not in lookup:
                    lookup[text] = (kind, key)
        for text in sorted(lookup, key=lambda t: (-len(t), t)):
            kind, _key = lookup[text]
            piece = re.escape(text).replace(r"\ ", r"\s+")
            pieces.append(piece + (r"(?:-\d{1,2})?" if _SPECS[kind].suffix else ""))
        parts = [f"(?P<email>{EMAIL_PATTERN})"]
        if pieces:
            parts.append(r"(?<!\w)(?P<value>" + "|".join(pieces) + r")(?!\w)")
        parts.append(r"(?P<digits>(?<![\w-])\d{6,}(?!\w))")
        self._scrub = re.compile("|".join(parts), re.IGNORECASE)
        self._scrub_lookup = lookup

    def _scrub_value(self, matched: str) -> str:
        text = " ".join(unicodedata.normalize("NFKC", matched).split()).casefold()
        found = self._scrub_lookup.get(text)
        if found is not None:
            kind, key = found
            return f"{_SPECS[kind].prefix}{self._vocab[kind][key]}"
        for kind in (Kind.INVOICE, Kind.RECEIPT):
            base, suffix = _split_suffix(kind, text)
            hit = self._scrub_lookup.get(base)
            if hit is not None and hit[0] is kind and suffix:
                return f"{_SPECS[kind].prefix}{self._vocab[kind][hit[1]]}{suffix}"
        return NUMBER_PLACEHOLDER

    def scrub_text(self, text: str | None) -> str | None:
        """Replace registered values with pseudonyms, emails and stray long numbers with tags."""
        if text is None:
            return None
        if self._scrub is None:
            raise PseudonymError("scrub before freeze")

        def replace(match: re.Match[str]) -> str:
            if match.group("email") is not None:
                return EMAIL_PLACEHOLDER
            if match.groupdict().get("value") is not None:
                return self._scrub_value(match.group("value"))
            return NUMBER_PLACEHOLDER

        return self._scrub.sub(replace, text)
