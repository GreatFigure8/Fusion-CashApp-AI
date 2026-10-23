"""Payer alias learning: normalisers, lookup for the matching stations, learn and retire.

A person's requeue teaches the system which customer a payer name, bank account or reference
pattern belongs to. Later items resolve through the alias. A key that points at more than one
customer is never auto-assigned: ``lookup`` returns every customer the matches point at.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Final, Protocol

from pydantic import JsonValue

from cashapp.data.models.aliases import PayerAlias
from cashapp.data.repositories.aliases import PayerAliasRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.paging import Page
from cashapp.domain.principal import Permission, Principal
from cashapp.domain.work_item import HistoryAction
from cashapp.services.actor import actor_fields
from cashapp.services.config import ConfigAudit
from cashapp.services.history import HistoryEntry, record_history

ALIAS_AUDIT_KEY: Final = "aliases"

LEGAL_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        "inc",
        "incorporated",
        "ltd",
        "limited",
        "llc",
        "llp",
        "plc",
        "pvt",
        "private",
        "gmbh",
        "co",
        "corp",
        "corporation",
        "company",
        "sa",
        "ag",
        "bv",
        "nv",
        "srl",
        "pte",
        "pty",
        "kk",
    }
)

MAX_PATTERN_LENGTH: Final = 200
MAX_REFERENCE_LENGTH: Final = 100
_REDOS_SHAPE: Final = re.compile(r"\([^()]*[+*][^()]*\)[+*{]")
_DELETED_PUNCTUATION: Final = str.maketrans("", "", ".'’")  # noqa: RUF001


# --------------------------------------------------------------------------- normalisers


def normalise_payer_name(name: str | None) -> str:
    """Canonical form of a payer name: folded, punctuation-free, without trailing legal suffixes."""
    if not name or not name.strip():
        return ""
    text = unicodedata.normalize("NFKC", name).casefold().replace("&", " and ")
    text = text.translate(_DELETED_PUNCTUATION)
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    tokens = text.split()
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalise_bank_account(value: str | None) -> str:
    """Canonical bank account: no whitespace, dashes or dots, upper-cased."""
    if not value:
        return ""
    return re.sub(r"[\s.\-]+", "", value).upper()


def validate_reference_pattern(pattern: str) -> str:
    """Return the stripped pattern, or raise ``InvalidReferencePattern``."""
    stripped = (pattern or "").strip()
    if not stripped:
        raise InvalidReferencePattern("The reference pattern is empty")
    if len(stripped) > MAX_PATTERN_LENGTH:
        raise InvalidReferencePattern(
            f"The reference pattern is longer than {MAX_PATTERN_LENGTH} characters"
        )
    try:
        compiled = re.compile(stripped)
    except re.error as exc:
        raise InvalidReferencePattern(f"The reference pattern is not a valid regex: {exc}") from exc
    if compiled.fullmatch(""):
        raise InvalidReferencePattern("The reference pattern matches everything")
    if _REDOS_SHAPE.search(stripped):
        raise InvalidReferencePattern("The reference pattern has nested quantifiers")
    return stripped


@lru_cache(maxsize=1024)
def _compiled(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern)
    except re.error:
        return None


# --------------------------------------------------------------------------- types and errors


class AliasKind(StrEnum):
    NAME = "name"
    BANK_ACCOUNT = "bank_account"
    REFERENCE = "reference"


class AliasError(Exception):
    """Base of every alias service error; the router maps these to the API error shape."""


class AliasNotFound(AliasError):  # noqa: N818 - pinned name
    def __init__(self, alias_id: int) -> None:
        self.alias_id = alias_id
        super().__init__(f"Alias {alias_id} not found")


class AliasForbidden(AliasError):  # noqa: N818 - pinned name
    def __init__(self, message: str, permission: Permission | None = None) -> None:
        self.permission = permission
        super().__init__(message)


class AliasValidationError(AliasError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InvalidReferencePattern(AliasValidationError):  # noqa: N818 - pinned name
    """The reference pattern is empty, invalid, too broad or unsafe."""


@dataclass(frozen=True, slots=True)
class AliasMatch:
    customer_numbers: tuple[str, ...] = ()  # sorted, unique; ALL customers the matches point at
    alias_ids: tuple[int, ...] = ()  # sorted, unique

    @property
    def is_empty(self) -> bool:
        return not self.alias_ids

    @property
    def customer_number(self) -> str | None:
        """Set only when exactly one customer matched; callers never auto-assign otherwise."""
        return self.customer_numbers[0] if len(self.customer_numbers) == 1 else None

    @property
    def is_ambiguous(self) -> bool:
        return len(self.customer_numbers) > 1


class AliasLookup(Protocol):
    async def lookup(
        self, payer_name: str | None, bank_account: str | None, references: Sequence[str]
    ) -> AliasMatch: ...


@dataclass(frozen=True, slots=True)
class LearnResult:
    aliases: tuple[PayerAlias, ...]  # one per key given (existing row when idempotent)
    created_ids: tuple[int, ...]
    conflict: bool  # some key now maps to more than one customer


# --------------------------------------------------------------------------- presentation


def alias_kind(alias: PayerAlias) -> AliasKind:
    if alias.payer_name_norm is not None:
        return AliasKind.NAME
    if alias.payer_bank_account is not None:
        return AliasKind.BANK_ACCOUNT
    return AliasKind.REFERENCE


def _mask(account: str) -> str:
    return "••••" + account[-4:]


def alias_text(alias: PayerAlias) -> str:
    """The alias key as shown to people; bank accounts are masked to the last four characters."""
    kind = alias_kind(alias)
    if kind is AliasKind.NAME:
        return alias.payer_name_norm or ""
    if kind is AliasKind.BANK_ACCOUNT:
        return _mask(alias.payer_bank_account or "")
    return alias.reference_pattern or ""


_KIND_LABELS: Final = {
    AliasKind.NAME: "payer name",
    AliasKind.BANK_ACCOUNT: "bank account",
    AliasKind.REFERENCE: "reference pattern",
}


def describe_alias(alias: PayerAlias) -> str:
    """One line for history reasoning and logs; never carries a full bank account number."""
    learned = ""
    if alias.learned_from_item_id is not None:
        learned = f"learned from item {alias.learned_from_item_id} by "
    else:
        learned = "learned by "
    text = (
        f"alias #{alias.id} ({_KIND_LABELS[alias_kind(alias)]} {alias_text(alias)} "
        f"→ customer {alias.customer_account_number}; "
        f"{learned}{alias.created_by_name} on {alias.created_at.date().isoformat()}"
    )
    if alias.retired_at is not None:
        text += f"; retired {alias.retired_at.date().isoformat()}"
    return text + ")"


def alias_json(alias: PayerAlias) -> dict[str, JsonValue]:
    """Audit snapshot of an alias (bank account masked)."""
    return {
        "id": alias.id,
        "kind": alias_kind(alias).value,
        "alias_text": alias_text(alias),
        "customer_number": alias.customer_account_number,
        "learned_from_item_id": alias.learned_from_item_id,
        "created_by": alias.created_by,
        "created_by_name": alias.created_by_name,
        "created_at": alias.created_at.isoformat(),
        "uses": alias.uses,
        "last_used_at": alias.last_used_at.isoformat() if alias.last_used_at else None,
        "retired_at": alias.retired_at.isoformat() if alias.retired_at else None,
        "retired_by": alias.retired_by,
        "retire_reason": alias.retire_reason,
    }


# --------------------------------------------------------------------------- service


class AliasService:
    """Satisfies ``AliasLookup``. ``lookup`` uses the bound unit of work; the rest take one."""

    def __init__(self, uow: UnitOfWork, *, clock: Clock | None = None) -> None:
        self._uow = uow
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def lookup(
        self, payer_name: str | None, bank_account: str | None, references: Sequence[str]
    ) -> AliasMatch:
        name_norm = normalise_payer_name(payer_name)
        bank_norm = normalise_bank_account(bank_account)
        refs = [ref.strip()[:MAX_REFERENCE_LENGTH] for ref in references if ref and ref.strip()]
        if not (name_norm or bank_norm or refs):
            return AliasMatch()

        repo = self._uow.repo(PayerAliasRepository)
        found: dict[int, PayerAlias] = {}
        if name_norm:
            for row in await repo.active_by_name(name_norm):
                found[row.id] = row
        if bank_norm:
            for row in await repo.active_by_bank_account(bank_norm):
                found[row.id] = row
        if refs:
            for row in await repo.active_reference_aliases():
                compiled = _compiled(row.reference_pattern or "")
                if compiled is not None and any(compiled.fullmatch(ref) for ref in refs):
                    found[row.id] = row
        if not found:
            return AliasMatch()

        ids = tuple(sorted(found))
        await repo.mark_used(ids, at=self._clock.now())
        customers = tuple(sorted({row.customer_account_number for row in found.values()}))
        return AliasMatch(customer_numbers=customers, alias_ids=ids)

    async def learn(
        self,
        uow: UnitOfWork,
        *,
        item_id: int,
        payer_name: str | None,
        bank_account: str | None,
        reference_pattern: str | None,
        customer_number: str,
        principal: Principal,
    ) -> LearnResult:
        """Store one alias row per key given. Never commits: the caller's transaction owns it."""
        if principal.is_system:
            raise AliasForbidden("Aliases are learned from human decisions only")
        if not principal.can(Permission.ITEMS_WORK):
            raise AliasForbidden(
                f"Missing permission {Permission.ITEMS_WORK.value}", Permission.ITEMS_WORK
            )
        customer = (customer_number or "").strip()
        if not customer:
            raise AliasValidationError("A customer number is required")

        keys: list[tuple[AliasKind, str]] = []
        name_norm = normalise_payer_name(payer_name)
        if name_norm:
            keys.append((AliasKind.NAME, name_norm))
        bank_norm = normalise_bank_account(bank_account)
        if bank_norm:
            keys.append((AliasKind.BANK_ACCOUNT, bank_norm))
        if reference_pattern is not None and reference_pattern.strip():
            keys.append((AliasKind.REFERENCE, validate_reference_pattern(reference_pattern)))
        if not keys:
            raise AliasValidationError("no alias key")

        repo = uow.repo(PayerAliasRepository)
        now = self._clock.now()
        aliases: list[PayerAlias] = []
        created: list[PayerAlias] = []
        conflicts: list[dict[str, JsonValue]] = []
        for kind, value in keys:
            existing = await repo.active_for_key(kind.value, value)
            same = next((row for row in existing if row.customer_account_number == customer), None)
            if same is not None:
                row = same
            else:
                row = await repo.add(
                    PayerAlias(
                        payer_name_norm=value if kind is AliasKind.NAME else None,
                        payer_bank_account=value if kind is AliasKind.BANK_ACCOUNT else None,
                        reference_pattern=value if kind is AliasKind.REFERENCE else None,
                        customer_account_number=customer,
                        learned_from_item_id=item_id,
                        created_by=principal.subject,
                        created_by_name=principal.display_name,
                        created_at=now,
                        uses=0,
                    )
                )
                created.append(row)
                existing = [*existing, row]
            aliases.append(row)
            customers = sorted({r.customer_account_number for r in existing})
            if len(customers) > 1:
                conflicts.append(
                    {
                        "alias_ids": [r.id for r in existing],
                        "customer_numbers": list(customers),
                    }
                )

        for row in created:
            await ConfigAudit.record(
                uow,
                ALIAS_AUDIT_KEY,
                None,
                alias_json(row),
                principal,
                f"learned from work item {item_id}",
                clock=self._clock,
            )

        if created:
            reasoning = [describe_alias(row) for row in created]
            for conflict in conflicts:
                names = ", ".join(str(n) for n in _as_list(conflict["customer_numbers"]))
                reasoning.append(
                    f"payer now maps to customers {names}; it will not be auto-assigned"
                )
            await record_history(
                uow,
                item_id,
                HistoryEntry(
                    action=HistoryAction.DECISION,
                    **actor_fields(principal),
                    reasoning="\n".join(reasoning),
                    payload={
                        "event": "alias_learned",
                        "alias_ids": [row.id for row in created],
                        "conflicts": conflicts,
                    },
                ),
                clock=self._clock,
            )

        return LearnResult(
            aliases=tuple(aliases),
            created_ids=tuple(row.id for row in created),
            conflict=bool(conflicts),
        )

    async def retire(
        self, uow: UnitOfWork, alias_id: int, principal: Principal, reason: str
    ) -> PayerAlias:
        if not principal.can(Permission.CONFIG_WRITE):
            raise AliasForbidden(
                f"Missing permission {Permission.CONFIG_WRITE.value}", Permission.CONFIG_WRITE
            )
        cleaned = (reason or "").strip()
        if not cleaned:
            raise AliasValidationError("A reason is required to retire an alias")

        repo = uow.repo(PayerAliasRepository)
        row = await repo.get_for_update(alias_id)
        if row is None:
            raise AliasNotFound(alias_id)
        if row.retired_at is not None:
            return row

        old = alias_json(row)
        row = await repo.update(
            row,
            retired_at=self._clock.now(),
            retired_by=principal.subject,
            retire_reason=cleaned,
        )
        await ConfigAudit.record(
            uow, ALIAS_AUDIT_KEY, old, alias_json(row), principal, cleaned, clock=self._clock
        )
        return row

    async def search(
        self,
        uow: UnitOfWork,
        *,
        active: bool | None = True,
        q: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[PayerAlias]:
        return await uow.repo(PayerAliasRepository).search(
            active=active, q=q, offset=offset, limit=limit
        )


def _as_list(value: JsonValue) -> list[JsonValue]:
    return value if isinstance(value, list) else []
