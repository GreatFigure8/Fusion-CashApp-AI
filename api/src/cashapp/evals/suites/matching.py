"""The matching suite: the prior build's messages replayed through today's matcher.

Customer resolution, receipt scoring and line planning run against a ``FakeFusionClient`` seeded
from the fixtures. No model is called. The prior outcomes and AR's labels came from a build with
known defects, so the report says *agreement*, never accuracy: a disagreement may mean the new
rules are right.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import RemittanceExtraction
from cashapp.domain.stages import Stage
from cashapp.domain.status import LineStatus
from cashapp.evals.models import (
    MatchingCaseResult,
    MatchingSuiteReport,
    Ratio,
    SuiteStatus,
)
from cashapp.evals.scoring import ConfusionCounter, normalise_ref
from cashapp.integrations.fusion.fake import FakeFusionClient
from cashapp.pipeline.errors import StageError
from cashapp.services.aliases import AliasMatch
from cashapp.services.config import ConfigSnapshot
from cashapp.services.customer import lookup_lines, resolve_customer
from cashapp.services.matching.lines import index_transactions, plan_lines
from cashapp.services.matching.receipts import MatchContext, score_candidates
from cashapp.tools.anonymise.fixture_format import (
    ExpectedDecision,
    PriorFixtures,
    PriorLabel,
    PriorMessage,
    expected_for,
)

__all__ = ["MessageReplay", "not_evaluated", "replay_message", "run_matching_suite", "today_of"]

LABEL_COLS: Final[tuple[str, ...]] = (
    "matched",
    "none",
    "ambiguous",
    "variance",
    "resolution_error",
)
_LABELS: Final[tuple[str, ...]] = tuple(label.value for label in PriorLabel)
_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in LineStatus)


class _NoAliases:
    """Alias learning is not under evaluation, and no aliases keeps the replay stateless."""

    async def lookup(
        self, payer_name: str | None, bank_account: str | None, references: Sequence[str]
    ) -> AliasMatch:
        return AliasMatch()


@dataclass(frozen=True, slots=True)
class MessageReplay:
    """What today's matcher does with one prior message."""

    outcome: str  # matched | none | ambiguous | variance | resolution_error
    error_code: ErrorCode | None
    stage: Stage  # the station that would raise ``error_code``
    receipt_id: int | None
    candidates: int
    line_status: Mapping[str, LineStatus | None]  # normalised transaction number -> verdict


def today_of(messages: list[PriorMessage]) -> date:
    """The latest payment date in the fixtures: the day the fake Fusion is 'now'."""
    dates = [m.extraction.payment_date.value for m in messages if m.extraction.payment_date.value]
    return max(dates) if dates else date.today()


def _findings_status(resolution_findings: Any) -> dict[str, LineStatus | None]:
    return {
        normalise_ref(f.transaction_number) or "": f.candidate_status for f in resolution_findings
    }


async def replay_message(
    message: PriorMessage, fusion_doc: Mapping[str, Any], config: ConfigSnapshot, *, today: date
) -> MessageReplay:
    """Customer resolution, receipt scoring and (on a match) line planning for one message."""
    # A fresh fake per message so nothing leaks from one replay to the next.
    fake = FakeFusionClient.from_json(fusion_doc, today=lambda: today)
    extraction: RemittanceExtraction = message.extraction
    matching = config.matching()

    try:
        resolution = await resolve_customer(extraction, aliases=_NoAliases(), fusion=fake)
    except StageError as exc:
        return MessageReplay("resolution_error", exc.code, Stage.RESOLVE_CUSTOMER, None, 0, {})
    findings = _findings_status(resolution.line_findings)

    payment_date = extraction.payment_date.value
    amount = extraction.payment_amount.value
    currency = resolution.currency
    if payment_date is None:
        return MessageReplay(
            "resolution_error", ErrorCode.MISSING_PAYMENT_DATE, Stage.VALIDATE, None, 0, findings
        )
    if amount is None or currency is None:
        return MessageReplay(
            "resolution_error", ErrorCode.EXTRACTION_FAILED, Stage.VALIDATE, None, 0, findings
        )

    window = timedelta(days=matching.date_window_days)
    receipts = await fake.find_receipts(
        customer_numbers=list(resolution.owners()),
        date_from=payment_date - window,
        date_to=payment_date + window,
    )
    ctx = MatchContext(
        payment_amount=amount,
        currency=currency,
        payment_date=payment_date,
        anchor=resolution.anchor_customer_number,
        related=resolution.related_customer_numbers,
        references=(
            (extraction.remittance_reference.value,)
            if extraction.remittance_reference.value
            else ()
        ),
        invoice_numbers=tuple(line.transaction_number.strip() for line in lookup_lines(extraction)),
        payer_bank_account=extraction.payer_bank_account.value,
        fix_hints={},
    )
    scored = score_candidates(ctx, receipts, matching, None)
    codes: dict[str, tuple[ErrorCode, Stage]] = {
        "none": (ErrorCode.RECEIPT_NOT_YET_AVAILABLE, Stage.MATCH_RECEIPT),
        "ambiguous": (ErrorCode.RECEIPT_AMBIGUOUS, Stage.MATCH_RECEIPT),
        "variance": (ErrorCode.AMOUNT_VARIANCE, Stage.MATCH_RECEIPT),
    }
    if scored.outcome != "matched" or scored.winner is None:
        code, stage = codes[scored.outcome]
        return MessageReplay(scored.outcome, code, stage, None, len(scored.candidates), findings)

    receipt = scored.winner.receipt
    existing = await fake.list_receipt_applications(receipt.receipt_id)
    transactions, ambiguous = index_transactions(
        resolution.transactions, lookup_lines(extraction), resolution.owners()
    )
    # The planner is given every line and skips fee, tariff and discount lines itself.
    plan = plan_lines(
        extraction.lines,
        transactions,
        receipt.unapplied_amount,
        existing,
        currency,
        header_amount=amount,
        tolerance=matching.tolerance_for(currency),
        owners=resolution.owners(),
        ambiguous=ambiguous,
    )
    status: dict[str, LineStatus | None] = dict(findings)
    by_line: dict[int, LineStatus] = {}
    for step in plan.steps:
        by_line[step.line_no] = step.target_status
        status[normalise_ref(step.transaction.number) or ""] = step.target_status
    for draft in plan.results:
        if draft.merged_into is None:
            by_line[draft.line_no] = draft.line_status
    for draft in plan.results:
        verdict = (
            by_line.get(draft.merged_into) if draft.merged_into is not None else draft.line_status
        )
        key = normalise_ref(draft.transaction_number) or ""
        if key:
            status[key] = verdict
    return MessageReplay(
        "matched", None, Stage.MATCH_LINES, receipt.receipt_id, len(scored.candidates), status
    )


def not_evaluated(reason: str) -> MatchingSuiteReport:
    """An empty report that says nothing was measured."""
    return MatchingSuiteReport(
        status=SuiteStatus.NOT_EVALUATED,
        reason=reason,
        messages=0,
        labelled=0,
        label_confusion=ConfusionCounter(_LABELS, LABEL_COLS).to_model(),
        label_agreement=Ratio.of(0, 0),
        agreement_by_label={},
        line_status_agreement=Ratio.of(0, 0),
        line_status_confusion=ConfusionCounter(_STATUSES, _STATUSES).to_model(),
        skipped={},
        per_case=[],
    )


def _expected_outcome(label: PriorLabel) -> str:
    """The single-snapshot matcher cannot tell the three 'no receipt yet' labels apart."""
    return "matched" if expected_for(label).decision is ExpectedDecision.MATCHED else "none"


async def run_matching_suite(
    prior: PriorFixtures, config: ConfigSnapshot, *, limit: int | None
) -> MatchingSuiteReport:
    """Replay up to ``limit`` messages; score agreement with AR's labels and prior line statuses."""
    messages = prior.messages if limit is None else prior.messages[:limit]
    if not messages:
        return not_evaluated("no prior messages found")
    today = today_of(prior.messages)
    known_ids = {m.message_id for m in prior.messages}
    labels = {f.message_id: f.label for f in prior.failures}
    skipped: dict[str, int] = {}
    orphans = sum(1 for f in prior.failures if f.message_id not in known_ids)
    if orphans:
        skipped["no_extraction"] = orphans

    label_matrix = ConfusionCounter(_LABELS, LABEL_COLS)
    status_matrix = ConfusionCounter(_STATUSES, _STATUSES)
    by_label: dict[str, list[int]] = {label: [0, 0] for label in _LABELS}  # [agree, total]
    status_agree = status_total = 0
    per_case: list[MatchingCaseResult] = []

    for message in messages:
        replay = await replay_message(message, prior.fusion, config, today=today)
        label = labels.get(message.message_id)
        agrees: bool | None = None
        if label is not None:
            label_matrix.add(label.value, replay.outcome)
            agrees = replay.outcome == _expected_outcome(label)
            by_label[label.value][1] += 1
            by_label[label.value][0] += int(agrees)
        per_case.append(
            MatchingCaseResult(
                message_id=message.message_id,
                label=label,
                outcome=replay.outcome,
                error_code=replay.error_code.value if replay.error_code else None,
                receipt_id=replay.receipt_id,
                candidates=replay.candidates,
                agrees=agrees,
            )
        )
        for line in message.outcome.lines:
            key = normalise_ref(line.transaction_number) or ""
            if key not in replay.line_status:
                skipped["number_not_found"] = skipped.get("number_not_found", 0) + 1
                continue
            predicted = replay.line_status[key]
            if predicted is None:
                skipped["no_verdict"] = skipped.get("no_verdict", 0) + 1
                continue
            status_matrix.add(line.line_status.value, predicted.value)
            status_total += 1
            status_agree += int(predicted is line.line_status)

    labelled = sum(total for _, total in by_label.values())
    return MatchingSuiteReport(
        status=SuiteStatus.EVALUATED,
        reason=None,
        messages=len(messages),
        labelled=labelled,
        label_confusion=label_matrix.to_model(),
        label_agreement=Ratio.of(sum(a for a, _ in by_label.values()), labelled),
        agreement_by_label={
            label: Ratio.of(agree, total) for label, (agree, total) in by_label.items() if total
        },
        line_status_agreement=Ratio.of(status_agree, status_total),
        line_status_confusion=status_matrix.to_model(),
        skipped=skipped,
        per_case=per_case,
    )
