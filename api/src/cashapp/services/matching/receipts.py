"""The receipt scorer: a pure function over Fusion receipts. No I/O, no database.

Hard filters decide who qualifies (currency, amount within tolerance or a bank-fee band, date
window, owner). Soft signals add score. The decision is never "first wins": exactly one
qualifier, or one that matches outright on a reference, or one that clearly beats its peers when
narrowing is allowed; anything else is ambiguous.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal

from cashapp.domain.money import money_eq, to_money
from cashapp.integrations.fusion.models import FusionReceipt

if TYPE_CHECKING:
    from cashapp.services.aliases import AliasMatch
    from cashapp.services.config_groups import MatchingConfig

# The soft signals the scorer weighs (hard filters carry no weight). Keyed exactly like the
# `matching.scorer_weights` setting and the s12 proposal.
SOFT_SIGNALS: Final[tuple[str, ...]] = (
    "remittance_reference",
    "statement_reference",
    "invoice_set_overlap",
    "payer_bank_account",
    "date_distance",
    "alias_reference_pattern",
    "customer_history",
)

OwnerTier = Literal["anchor", "related", "other"]
Outcome = Literal["matched", "none", "ambiguous", "variance"]

_ZERO: Final = Decimal("0.00")
_WILDCARD: Final = "*"
_TOKEN_SPLIT: Final = re.compile(r"[\s,;:/|()\[\]]+")
_TIER_ORDER: Final[dict[str, int]] = {"anchor": 0, "related": 1, "other": 2}

# Hard-filter failure keys (internal); the public reasons are strings built from them.
_F_CURRENCY: Final = "currency"
_F_AMOUNT: Final = "amount"
_F_WINDOW: Final = "window"
_F_OWNER: Final = "owner"


@dataclass(frozen=True, slots=True)
class MatchContext:
    payment_amount: Decimal
    currency: str
    payment_date: date
    anchor: str
    related: tuple[str, ...] = ()
    references: tuple[str, ...] = ()  # remittance reference(s) from the extraction
    invoice_numbers: tuple[str, ...] = ()  # INVOICE / CREDIT_MEMO transaction numbers
    payer_bank_account: str | None = None
    fix_hints: Mapping[str, Any] = MappingProxyType({})
    # receipt_id -> amount already applied from it to this remittance (partial-apply resume)
    resume_applied: Mapping[int, Decimal] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ReceiptEvidence:
    receipt_id: int
    statement_reference: str | None = None
    payer_bank_account: str | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    receipt: FusionReceipt
    qualifies: bool
    score: float
    signals: dict[str, float]
    reasons: list[str]
    amount_diff: Decimal
    owner_tier: OwnerTier


@dataclass(frozen=True, slots=True)
class ScoredCandidates:
    candidates: list[Candidate]
    winner: Candidate | None
    outcome: Outcome
    rule: str | None = None


def normalise_reference(value: str) -> str:
    """Upper-case, no whitespace, no leading '#'. A '-' suffix is kept (it marks a credit memo)."""
    text = "".join(value.split()).upper()
    return text.removeprefix("#")


def _normalise_all(values: Sequence[str]) -> frozenset[str]:
    return frozenset(n for n in (normalise_reference(v) for v in values) if n)


def _normalise_account(value: str | None) -> str:
    return "".join(value.split()).upper() if value else ""


def _comment_tokens(comments: str | None) -> frozenset[str]:
    if not comments:
        return frozenset()
    return _normalise_all([t for t in _TOKEN_SPLIT.split(comments) if t])


def _in_band(fee: Decimal, currency: str, config: MatchingConfig) -> bool:
    for band in config.bank_fee_bands:
        if band.currency not in (currency, _WILDCARD):
            continue
        if band.min_fee <= fee <= band.max_fee:
            return True
    return False


@dataclass(slots=True)
class _Work:
    receipt: FusionReceipt
    failed: set[str]
    reasons: list[str]
    hard: dict[str, float]
    diff: Decimal
    tier: OwnerTier
    distance: int | None  # smallest qualifying day distance
    soft: dict[str, float]
    score: float = 0.0
    exact_set: bool = False

    @property
    def qualifies(self) -> bool:
        return not self.failed


def _apply_amount(
    work: _Work, ctx: MatchContext, config: MatchingConfig, effective: Decimal, resumed: bool
) -> None:
    unapplied = work.receipt.unapplied_amount
    work.diff = to_money(unapplied - effective)
    if resumed and effective <= Decimal("0.005"):
        work.hard["resume_fully_applied"] = 1.0
        return
    if abs(work.diff) <= config.tolerance_for(ctx.currency):
        work.hard["amount_exact" if money_eq(unapplied, effective) else "amount_tolerance"] = 1.0
        return
    if _in_band(to_money(effective - unapplied), ctx.currency, config):
        work.hard["bank_fee_band"] = 1.0
        return
    work.failed.add(_F_AMOUNT)
    work.reasons.append(f"{_AMOUNT_REASON}:{work.diff}")


def _apply_window(work: _Work, ctx: MatchContext, window: int) -> None:
    receipt = work.receipt
    by_receipt = abs((receipt.receipt_date - ctx.payment_date).days)
    by_creation = abs((receipt.creation_date.date() - ctx.payment_date).days)
    if by_receipt <= window:
        work.hard["date_receipt_window"] = 1.0
        work.distance = by_receipt
        if ctx.fix_hints.get("match_on_creation_date") and by_creation <= window:
            work.distance = min(by_receipt, by_creation)
    elif ctx.fix_hints.get("match_on_creation_date") and by_creation <= window:
        work.hard["date_creation_window"] = 1.0
        work.distance = by_creation
    else:
        work.failed.add(_F_WINDOW)
        work.reasons.append("outside_window")


def _soft_signals(
    work: _Work,
    ctx: MatchContext,
    window: int,
    aliases: AliasMatch | None,
    evidence: ReceiptEvidence | None,
) -> None:
    receipt = work.receipt
    refs = _normalise_all(receipt.remittance_references)
    tokens = refs | _comment_tokens(receipt.comments)
    wanted = _normalise_all(ctx.references)
    invoices = _normalise_all(ctx.invoice_numbers)

    soft = work.soft
    soft["remittance_reference"] = 1.0 if wanted & tokens else 0.0
    statement = (
        normalise_reference(evidence.statement_reference)
        if evidence and evidence.statement_reference
        else ""
    )
    soft["statement_reference"] = 1.0 if statement and statement in wanted else 0.0
    soft["invoice_set_overlap"] = len(invoices & tokens) / len(invoices) if invoices else 0.0
    payer = _normalise_account(ctx.payer_bank_account)
    on_receipt = _normalise_account(evidence.payer_bank_account) if evidence else ""
    soft["payer_bank_account"] = 1.0 if payer and payer == on_receipt else 0.0
    soft["date_distance"] = (
        max(0.0, 1.0 - work.distance / (window + 1)) if work.distance is not None else 0.0
    )
    owner = receipt.customer_account_number
    soft["alias_reference_pattern"] = (
        1.0
        if aliases is not None and owner is not None and owner in aliases.customer_numbers
        else 0.0
    )
    soft["customer_history"] = {"anchor": 1.0, "related": 0.5, "other": 0.0}[work.tier]
    work.exact_set = bool(invoices) and invoices == refs


def _score_receipt(
    receipt: FusionReceipt,
    ctx: MatchContext,
    config: MatchingConfig,
    aliases: AliasMatch | None,
    evidence: ReceiptEvidence | None,
    window: int,
) -> _Work:
    owner = receipt.customer_account_number
    tier: OwnerTier = "other"
    if owner is not None and owner == ctx.anchor:
        tier = "anchor"
    elif owner is not None and owner in ctx.related:
        tier = "related"
    work = _Work(
        receipt=receipt,
        failed=set(),
        reasons=[],
        hard={},
        diff=_ZERO,
        tier=tier,
        distance=None,
        soft={},
    )

    if receipt.currency.upper() != ctx.currency.upper():
        work.failed.add(_F_CURRENCY)
        work.reasons.append("currency_mismatch")

    applied = ctx.resume_applied.get(receipt.receipt_id)
    effective = ctx.payment_amount - applied if applied is not None else ctx.payment_amount
    _apply_amount(work, ctx, config, effective, applied is not None)
    _apply_window(work, ctx, window)

    if tier == "other":
        work.failed.add(_F_OWNER)
        work.reasons.append("not_owner")
    else:
        work.hard["owner_anchor" if tier == "anchor" else "owner_related"] = 1.0

    _soft_signals(work, ctx, window, aliases, evidence)
    weights = config.scorer_weights
    work.score = round(sum(weights.get(k, 0.0) * work.soft[k] for k in SOFT_SIGNALS), 6)
    return work


def _to_candidate(work: _Work) -> Candidate:
    return Candidate(
        receipt=work.receipt,
        qualifies=work.qualifies,
        score=work.score,
        signals={**work.soft, **work.hard},
        reasons=list(work.reasons),
        amount_diff=work.diff,
        owner_tier=work.tier,
    )


def _display_key(work: _Work) -> tuple[int, int, float, Decimal, int]:
    return (
        0 if work.qualifies else 1,
        _TIER_ORDER[work.tier],
        -work.score,
        abs(work.diff),
        work.receipt.receipt_id,
    )


_AMOUNT_REASON: Final = "amount_outside_tolerance"


def _is_grounded(signals: Mapping[str, float]) -> bool:
    """The receipt carries something of this remittance: a reference, a bank account, an invoice."""
    return (
        signals.get("remittance_reference", 0.0) == 1.0
        or signals.get("statement_reference", 0.0) == 1.0
        or signals.get("payer_bank_account", 0.0) == 1.0
        or signals.get("invoice_set_overlap", 0.0) > 0.0
    )


def variance_candidate(candidates: Sequence[Candidate]) -> Candidate | None:
    """A grounded receipt that failed only the amount filter (an amount-only near miss)."""
    for candidate in candidates:
        only_amount = len(candidate.reasons) == 1 and candidate.reasons[0].startswith(
            _AMOUNT_REASON
        )
        if not candidate.qualifies and only_amount and _is_grounded(candidate.signals):
            return candidate
    return None


def _decide(
    qualifiers: list[_Work], ctx: MatchContext, config: MatchingConfig
) -> tuple[Outcome, _Work | None, str | None]:
    """Pick the winner among qualifiers, or say why there is none. Never first-wins."""
    if not qualifiers:
        return "none", None, None
    pool = qualifiers
    outright = [
        w
        for w in qualifiers
        if w.soft["remittance_reference"] == 1.0
        or w.soft["statement_reference"] == 1.0
        or w.exact_set
    ]
    if len(outright) == 1:
        return "matched", outright[0], "outright"
    if outright:
        pool = outright
    elif len(pool) == 1:
        return "matched", pool[0], "single"

    anchors = [w for w in pool if w.tier == "anchor"]
    tier, rule = (anchors, "tier_anchor") if anchors else (pool, "tier_related")
    if len(tier) == 1:
        return "matched", tier[0], rule

    if ctx.fix_hints.get("narrow"):
        ranked = sorted(tier, key=lambda w: (-w.score, w.receipt.receipt_id))
        best, runner_up = ranked[0], ranked[1]
        if best.score > runner_up.score and best.score - runner_up.score >= config.min_score:
            return "matched", best, "narrowed"
    return "ambiguous", None, None


def score_candidates(
    ctx: MatchContext,
    receipts: Sequence[FusionReceipt],
    config: MatchingConfig,
    aliases: AliasMatch | None,
    *,
    evidence: Mapping[int, ReceiptEvidence] | None = None,
) -> ScoredCandidates:
    """Score every receipt and decide. Receipts are deduplicated by ``receipt_id``."""
    window = config.date_window_days + int(ctx.fix_hints.get("widen_window_days", 0) or 0)
    pool: dict[int, FusionReceipt] = {}
    for receipt in receipts:
        pool.setdefault(receipt.receipt_id, receipt)

    works = [
        _score_receipt(r, ctx, config, aliases, (evidence or {}).get(r.receipt_id), window)
        for r in pool.values()
    ]
    works.sort(key=_display_key)

    outcome, winner, rule = _decide([w for w in works if w.qualifies], ctx, config)
    candidates = [_to_candidate(w) for w in works]
    if outcome == "none" and variance_candidate(candidates) is not None:
        outcome = "variance"
    chosen = next((c for w, c in zip(works, candidates, strict=True) if w is winner), None)
    return ScoredCandidates(candidates=candidates, winner=chosen, outcome=outcome, rule=rule)
