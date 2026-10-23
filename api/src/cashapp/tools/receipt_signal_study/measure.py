"""Presence, precision, ambiguity and miss rate per signal; date-distance histograms."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from cashapp.tools.receipt_signal_study.models import (
    CIRCULAR_IN_FUSION_MODE,
    SIGNALS,
    CaseSource,
    SignalName,
    SignalStat,
    StudyCase,
    StudyReceipt,
)
from cashapp.tools.receipt_signal_study.signals import SignalContext, candidate_matches

DATE_BUCKETS: tuple[str, ...] = ("0", "1", "2", "3-5", ">5")
_RATE_DIGITS = 4


def _rate(count: int, total: int) -> float | None:
    return round(count / total, _RATE_DIGITS) if total else None


def _bucket(days: int) -> str:
    if days <= 2:
        return str(days)
    return "3-5" if days <= 5 else ">5"


def measure_signal(
    signal: SignalName,
    cases: Sequence[StudyCase],
    pool: Mapping[int, StudyReceipt],
    ctx: SignalContext,
    *,
    circular: bool = False,
) -> SignalStat:
    present = unique = ambiguous = missed = 0
    candidates = list(pool.values())
    for case in cases:
        truth = pool.get(case.truth_receipt_id)
        if truth is None or candidate_matches(signal, case, truth, ctx) is None:
            continue
        present += 1
        matched = [c.receipt_id for c in candidates if candidate_matches(signal, case, c, ctx)]
        if case.truth_receipt_id not in matched:
            missed += 1
        elif len(matched) == 1:
            unique += 1
        else:
            ambiguous += 1
    return SignalStat(
        signal=signal,
        present=present,
        cases=len(cases),
        presence_rate=_rate(present, len(cases)),
        precision=_rate(unique, present),
        ambiguous_rate=_rate(ambiguous, present),
        miss_rate=_rate(missed, present),
        circular=circular,
        skipped_reason=None,
    )


def measure(
    cases: Sequence[StudyCase],
    pool: Mapping[int, StudyReceipt],
    ctx: SignalContext,
    *,
    case_source: CaseSource = "fusion",
    skipped: Mapping[SignalName, str] | None = None,
) -> list[SignalStat]:
    """One `SignalStat` per signal, in `SIGNALS` order. Skipped signals carry null rates."""
    skipped = skipped or {}
    stats: list[SignalStat] = []
    for signal in SIGNALS:
        circular = case_source == "fusion" and signal in CIRCULAR_IN_FUSION_MODE
        reason = skipped.get(signal)
        if reason is not None:
            stats.append(
                SignalStat(
                    signal=signal,
                    present=0,
                    cases=len(cases),
                    presence_rate=None,
                    precision=None,
                    ambiguous_rate=None,
                    miss_rate=None,
                    circular=circular,
                    skipped_reason=reason,
                )
            )
            continue
        stats.append(measure_signal(signal, cases, pool, ctx, circular=circular))
    return stats


def date_distance_histogram(
    cases: Sequence[StudyCase], pool: Mapping[int, StudyReceipt]
) -> dict[Literal["receipt_date", "creation_date"], dict[str, int]]:
    """Days between the payment date and the truth receipt's date, by both date bases."""
    receipt_hist = dict.fromkeys(DATE_BUCKETS, 0)
    creation_hist = dict.fromkeys(DATE_BUCKETS, 0)
    for case in cases:
        truth = pool.get(case.truth_receipt_id)
        if truth is None:
            continue
        receipt_hist[_bucket(abs((truth.receipt.receipt_date - case.payment_date).days))] += 1
        creation_hist[
            _bucket(abs((truth.receipt.creation_date.date() - case.payment_date).days))
        ] += 1
    return {"receipt_date": receipt_hist, "creation_date": creation_hist}
