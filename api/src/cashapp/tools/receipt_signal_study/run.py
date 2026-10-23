"""Orchestration: collect -> measure. The client is passed in and wrapped read-only here."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from cashapp.integrations.fusion import FusionClient, FusionError, read_only
from cashapp.integrations.fusion.xmlutil import XmlParseError
from cashapp.tools.receipt_signal_study.collect import (
    accounts_of,
    build_cases_from_fusion,
    build_cases_from_prior,
    build_study_receipts,
    collect_applications,
    collect_receipts,
    collect_relationships,
    collect_statement_signals,
    collect_transactions,
    prior_numbers,
    references_of,
    utc_midnight,
)
from cashapp.tools.receipt_signal_study.measure import date_distance_histogram, measure
from cashapp.tools.receipt_signal_study.models import (
    STATEMENT_SIGNALS,
    CaseSource,
    SignalName,
    StatementSignals,
    StudyCase,
    StudyResult,
)
from cashapp.tools.receipt_signal_study.signals import (
    SignalContext,
    default_date_window_days,
    default_tolerances,
)

NO_REPORT_REASON = "no receipt_signals report (s32 catalog)"
BAD_REPORT_REASON = "receipt_signals report could not be read"
MAX_CASES = 2000


def _sample(cases: list[StudyCase], limit: int) -> list[StudyCase]:
    """An even, deterministic sample so measuring stays bounded on a busy pod."""
    if len(cases) <= limit:
        return cases
    stride = len(cases) / limit
    return [cases[int(i * stride)] for i in range(limit)]


async def run_study(
    client: FusionClient,
    *,
    date_from: date,
    date_to: date,
    date_window_days: int | None = None,
    tolerances: Mapping[str, Decimal] | None = None,
    signals_report_path: str | None = None,
    prior_dir: Path | None = None,
    limit_receipts: int = 20_000,
    max_cases: int = MAX_CASES,
) -> StudyResult:
    """Measure how well each signal alone identifies the receipt that was actually applied."""
    client = read_only(client)
    window = default_date_window_days() if date_window_days is None else date_window_days
    tolerance_map = dict(tolerances) if tolerances is not None else default_tolerances()
    case_source: CaseSource = "prior" if prior_dir is not None else "fusion"

    # Receipts are selected by creation time (they are often created a day after their date).
    created_from = utc_midnight(date_from - timedelta(days=window))
    created_to = utc_midnight(date_to + timedelta(days=window + 2))
    receipts = await collect_receipts(
        client, created_from=created_from, created_to=created_to, limit=limit_receipts
    )
    in_range = [r for r in receipts if date_from <= r.receipt_date <= date_to]

    skipped: dict[SignalName, str] = {}
    statements: dict[int, StatementSignals] = {}
    if signals_report_path is None:
        skipped = dict.fromkeys(STATEMENT_SIGNALS, NO_REPORT_REASON)
    else:
        try:
            statements = await collect_statement_signals(
                client, signals_report_path, created_from=created_from, created_to=created_to
            )
        except FusionError:
            skipped = dict.fromkeys(STATEMENT_SIGNALS, NO_REPORT_REASON)
        except XmlParseError:
            skipped = dict.fromkeys(STATEMENT_SIGNALS, BAD_REPORT_REASON)

    truth_pool = receipts if case_source == "prior" else in_range
    applications = await collect_applications(client, (r.receipt_id for r in truth_pool))

    numbers = references_of(receipts)
    if prior_dir is not None:
        numbers |= prior_numbers(prior_dir)
    transactions = await collect_transactions(client, numbers)

    pool = build_study_receipts(
        receipts, applications=applications, statements=statements, transactions=transactions
    )
    if prior_dir is not None:
        cases = build_cases_from_prior(prior_dir, pool, transactions=transactions)
    else:
        cases = build_cases_from_fusion(
            pool, date_from=date_from, date_to=date_to, transactions=transactions
        )
    cases = _sample(cases, max_cases)

    related = await collect_relationships(client, accounts_of(cases))
    ctx = SignalContext(date_window_days=window, tolerances=tolerance_map, related=related)
    stats = measure(cases, pool, ctx, case_source=case_source, skipped=skipped)

    return StudyResult(
        pod=client.pod_name,
        date_from=date_from,
        date_to=date_to,
        case_source=case_source,
        receipts=len(in_range),
        pool=len(pool),
        cases=len(cases),
        date_window_days=window,
        stats=tuple(stats),
        date_distance=date_distance_histogram(cases, pool),
        provisional=client.pod_name == "fake",
        tolerances=tolerance_map,
    )
