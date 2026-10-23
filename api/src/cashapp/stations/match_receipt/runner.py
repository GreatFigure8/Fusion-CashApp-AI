"""The match-receipt station: finds the one Fusion receipt that paid this remittance.

Every receipt looked at is written to MATCH_CANDIDATE (committed before any failure is raised, so
the trail survives), the winner is reserved, and the reason is recorded as a DECISION history row.
"""

import inspect
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any, ClassVar, NoReturn, Self

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.adjudication import AdjudicationRepository
from cashapp.data.repositories.customer_resolution import CustomerResolutionRepository
from cashapp.data.repositories.match_candidates import CandidateRow, MatchCandidateRepository
from cashapp.data.repositories.reservations import ReservationRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.customer import CustomerResolution
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import LineKind, RemittanceExtraction
from cashapp.domain.money import to_money
from cashapp.domain.receipt_matching import DecidedBy
from cashapp.domain.stages import Stage
from cashapp.domain.work_item import HistoryAction
from cashapp.integrations.fusion.client import FusionClient, ReceiptDateBasis
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import FusionReceipt
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.outcomes import Advance, StageOutcome
from cashapp.pipeline.roles import Container
from cashapp.pipeline.runner import RunnerDeps, StageContext, StageRunner, consumer_role
from cashapp.services.aliases import AliasLookup, AliasMatch
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.matching.evidence import fetch_receipt_evidence
from cashapp.services.matching.receipts import (
    Candidate,
    MatchContext,
    ScoredCandidates,
    score_candidates,
    variance_candidate,
)
from cashapp.services.matching.reservations import ReservationService
from cashapp.stations.resolve_customer.runner import default_alias_lookup

AliasFactory = Callable[[UnitOfWork], AliasLookup]

_CENT_FLOOR = Decimal("0.005")
_APPLICATION_REVERSED = "REVERSED"


def _text(value: str | None) -> str | None:
    stripped = value.strip() if value else ""
    return stripped or None


def _extraction_inputs(
    extraction: RemittanceExtraction | None,
) -> tuple[tuple[str, ...], tuple[str, ...], str | None, str | None]:
    """References, invoice/credit-memo numbers, payer name and payer bank account."""
    if extraction is None:
        return (), (), None, None
    reference = _text(extraction.remittance_reference.value)
    numbers = tuple(
        dict.fromkeys(
            line.transaction_number.strip()
            for line in extraction.lines
            if line.kind in (LineKind.INVOICE, LineKind.CREDIT_MEMO)
            and line.transaction_number.strip()
        )
    )
    return (
        (reference,) if reference else (),
        numbers,
        _text(extraction.payer_name.value),
        _text(extraction.payer_bank_account.value),
    )


class MatchReceiptRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.MATCH_RECEIPT

    def __init__(
        self,
        deps: RunnerDeps,
        *,
        fusion: FusionClient,
        alias_lookup: AliasFactory | None = None,
        reservations: ReservationService | None = None,
    ) -> None:
        super().__init__(deps)
        self._fusion = fusion
        self._alias_lookup: AliasFactory = alias_lookup or default_alias_lookup
        self._reservations = reservations or ReservationService(deps.clock)

    @classmethod
    def build(cls, container: Container) -> Self:
        return cls(RunnerDeps.from_container(container), fusion=container.resolve(FusionClient))

    # --- inputs ----------------------------------------------------------------------------

    async def _resume_applied(
        self, uow: UnitOfWork, item: WorkItem, resolution: CustomerResolution
    ) -> tuple[int | None, dict[int, Decimal]]:
        """The receipt this item already holds or chose, and what Fusion shows applied from it."""
        prior_id: int | None = None
        active = await uow.repo(ReservationRepository).active_for_item(item.id)
        if active is not None:
            prior_id = active.receipt_id
        else:
            chosen = await uow.repo(MatchCandidateRepository).last_chosen(item.id)
            if chosen is not None:
                prior_id = chosen.receipt_id
        if prior_id is None:
            return None, {}
        ours = {t.customer_trx_id for t in resolution.transactions}
        applications = await self._fusion.list_receipt_applications(prior_id)
        applied = sum(
            (
                a.amount_applied
                for a in applications
                if a.status != _APPLICATION_REVERSED and a.customer_trx_id in ours
            ),
            Decimal("0.00"),
        )
        return prior_id, ({prior_id: to_money(applied)} if applied else {})

    async def _search(
        self,
        item: WorkItem,
        resolution: CustomerResolution,
        payment_date: Any,
        window: int,
        by_creation_date: bool,
    ) -> dict[int, FusionReceipt]:
        pool: dict[int, FusionReceipt] = {}
        bases: list[ReceiptDateBasis] = ["receipt_date"]
        if by_creation_date:
            bases.append("creation_date")
        for basis in bases:
            found = await self._fusion.find_receipts(
                customer_numbers=list(resolution.owners()),
                date_from=payment_date - timedelta(days=window),
                date_to=payment_date + timedelta(days=window),
                by=basis,
            )
            for receipt in found:
                pool.setdefault(receipt.receipt_id, receipt)
        return pool

    async def _add_known(self, pool: dict[int, FusionReceipt], receipt_id: int | None) -> None:
        """Pull a specific receipt into the pool when the search did not return it."""
        if receipt_id is None or receipt_id in pool:
            return
        try:
            pool[receipt_id] = await self._fusion.get_receipt(receipt_id)
        except FusionError:
            return

    async def _aliases(
        self,
        ctx: StageContext,
        payer_name: str | None,
        bank_account: str | None,
        references: tuple[str, ...],
    ) -> AliasMatch | None:
        # Aliases only add score, so a failure here must never fail the match.
        try:
            lookup: Any = self._alias_lookup(ctx.uow).lookup(payer_name, bank_account, references)
            match: AliasMatch = await lookup if inspect.isawaitable(lookup) else lookup
        except Exception:
            ctx.log.warning("alias_lookup_failed")
            return None
        return match

    # --- persistence -----------------------------------------------------------------------

    @staticmethod
    def _rows(
        scored: ScoredCandidates, chosen_id: int | None, decided_by: DecidedBy
    ) -> list[CandidateRow]:
        return [
            CandidateRow(
                receipt_id=c.receipt.receipt_id,
                receipt_number=c.receipt.receipt_number,
                qualifies=c.qualifies,
                score=c.score,
                signals=c.signals,
                reasons=c.reasons,
                chosen=c.receipt.receipt_id == chosen_id,
                decided_by=decided_by if c.receipt.receipt_id == chosen_id else DecidedBy.SYSTEM,
                customer_account_number=c.receipt.customer_account_number,
                currency=c.receipt.currency,
                receipt_date=c.receipt.receipt_date,
                unapplied_amount=c.receipt.unapplied_amount,
            )
            for c in scored.candidates
        ]

    # --- the step --------------------------------------------------------------------------

    async def process(self, ctx: StageContext) -> StageOutcome:
        uow, item = ctx.uow, ctx.item
        resolution = await uow.repo(CustomerResolutionRepository).latest_for(item.id)
        if resolution is None:
            raise StageError(ErrorCode.CUSTOMER_NOT_FOUND, {"reason": "no_resolution"})
        if item.payment_date is None:
            raise StageError(ErrorCode.MISSING_PAYMENT_DATE)
        currency = resolution.currency or item.currency
        if currency is None:
            raise StageError(ErrorCode.INVALID_CURRENCY, {"reason": "no_currency"})
        if item.payment_amount is None:
            raise StageError(ErrorCode.EXTRACTION_FAILED, {"reason": "no_payment_amount"})

        adjudication = await uow.repo(AdjudicationRepository).latest_for(item.id)
        extraction = (
            RemittanceExtraction.model_validate(adjudication.final)
            if adjudication is not None and adjudication.final is not None
            else None
        )
        references, invoice_numbers, payer_name, bank_account = _extraction_inputs(extraction)

        matching = ctx.config.matching()
        hints: dict[str, Any] = dict(item.fix_hints or {})
        window = matching.date_window_days + int(hints.get("widen_window_days", 0) or 0)

        prior_id, resume_applied = await self._resume_applied(uow, item, resolution)
        pool = await self._search(
            item, resolution, item.payment_date, window, bool(hints.get("match_on_creation_date"))
        )
        await self._add_known(pool, prior_id)
        human_id: int | None = (item.human_hints or {}).get("receipt_id")
        await self._add_known(pool, human_id)

        aliases = await self._aliases(ctx, payer_name, bank_account, references)
        evidence = await fetch_receipt_evidence(self._fusion, list(pool.values()), log=ctx.log)
        match_ctx = MatchContext(
            payment_amount=item.payment_amount,
            currency=currency,
            payment_date=item.payment_date,
            anchor=resolution.anchor_customer_number,
            related=resolution.related_customer_numbers,
            references=references,
            invoice_numbers=invoice_numbers,
            payer_bank_account=bank_account,
            fix_hints=hints,
            resume_applied=resume_applied,
        )
        scored = score_candidates(
            match_ctx, list(pool.values()), matching, aliases, evidence=evidence
        )

        winner, decided_by, rule = scored.winner, DecidedBy.SYSTEM, scored.rule
        human_problem: str | None = None
        if human_id is not None:
            winner = next((c for c in scored.candidates if c.receipt.receipt_id == human_id), None)
            decided_by, rule = DecidedBy.HUMAN, "human"
            if winner is None:
                human_problem = "not_found"
            elif winner.receipt.currency.upper() != currency.upper():
                human_problem = "currency_mismatch"
            elif winner.receipt.unapplied_amount <= _CENT_FLOOR:
                human_problem = "no_unapplied"

        # The audit trail is committed first, so it survives the StageError raised below.
        repo = uow.repo(MatchCandidateRepository)
        attempt = await repo.next_attempt(item.id)
        chosen_id = (
            winner.receipt.receipt_id if winner is not None and human_problem is None else None
        )
        await repo.add_round(
            item.id, attempt, self._rows(scored, chosen_id, decided_by), now=ctx.clock.now()
        )
        await uow.commit()

        if human_problem is not None:
            raise StageError(
                ErrorCode.AMOUNT_VARIANCE,
                {"human_receipt_id": human_id, "reason": human_problem},
            )
        if winner is None:
            self._raise_unmatched(scored, window)
        assert rule is not None  # noqa: S101 - set whenever a winner exists

        receipt = winner.receipt
        claim = await self._reservations.claim(
            uow,
            item=item,
            receipt_id=receipt.receipt_id,
            receipt_number=receipt.receipt_number,
            now=ctx.clock.now(),
        )
        payload = self._decision_payload(
            winner, scored, decided_by, rule, aliases, window, resume_applied, attempt
        )
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.DECISION,
                reasoning=self._reasoning(winner, rule, decided_by, claim.released_own_receipt_id),
                payload=payload,
            ),
            clock=ctx.clock,
        )
        ctx.log.info(
            "receipt matched",
            extra={
                "receipt_id": receipt.receipt_id,
                "rule": rule,
                "candidates": len(scored.candidates),
            },
        )
        return Advance(
            Stage.MATCH_LINES,
            note=f"receipt {receipt.receipt_number}",
            payload={"receipt_id": receipt.receipt_id},
        )

    # --- outcomes --------------------------------------------------------------------------

    @staticmethod
    def _raise_unmatched(scored: ScoredCandidates, window: int) -> NoReturn:
        qualifying = [c for c in scored.candidates if c.qualifies]
        if scored.outcome == "ambiguous":
            ranked = sorted((c.score for c in qualifying), reverse=True)
            raise StageError(
                ErrorCode.RECEIPT_AMBIGUOUS,
                {
                    "receipt_ids": [c.receipt.receipt_id for c in qualifying],
                    "best_score": ranked[0],
                    "runner_up_score": ranked[1] if len(ranked) > 1 else None,
                },
            )
        if scored.outcome == "variance":
            near = variance_candidate(scored.candidates)
            raise StageError(
                ErrorCode.AMOUNT_VARIANCE,
                {
                    "receipt_id": near.receipt.receipt_id if near else None,
                    "amount_diff": str(near.amount_diff) if near else None,
                },
            )
        raise StageError(
            ErrorCode.RECEIPT_NOT_YET_AVAILABLE,
            {"candidates": len(scored.candidates), "window_days": window},
        )

    @staticmethod
    def _decision_payload(
        winner: Candidate,
        scored: ScoredCandidates,
        decided_by: DecidedBy,
        rule: str,
        aliases: AliasMatch | None,
        window: int,
        resume_applied: dict[int, Decimal],
        attempt: int,
    ) -> dict[str, Any]:
        others = [
            c.score
            for c in scored.candidates
            if c.qualifies and c.receipt.receipt_id != winner.receipt.receipt_id
        ]
        resumed = resume_applied.get(winner.receipt.receipt_id, Decimal("0.00"))
        return {
            "receipt_id": winner.receipt.receipt_id,
            "receipt_number": winner.receipt.receipt_number,
            "decided_by": decided_by.value,
            "rule": rule,
            "score": winner.score,
            "runner_up_score": max(others) if others else None,
            "signals": winner.signals,
            "reasons": winner.reasons,
            "alias_ids": list(aliases.alias_ids) if aliases is not None else [],
            "window_days": window,
            "basis": "creation_date"
            if "date_creation_window" in winner.signals
            else "receipt_date",
            "resume_applied": str(resumed),
            "match_attempt": attempt,
        }

    @staticmethod
    def _reasoning(
        winner: Candidate, rule: str, decided_by: DecidedBy, released_own: int | None
    ) -> str:
        number = winner.receipt.receipt_number
        if decided_by is DecidedBy.HUMAN:
            text = f"Receipt {number} chosen by a person at requeue"
        else:
            text = {
                "outright": f"Receipt {number} matched outright on its reference or invoice set",
                "single": f"Receipt {number} is the only receipt that qualifies",
                "tier_anchor": f"Receipt {number} is the only qualifying anchor-customer receipt",
                "tier_related": f"Receipt {number} is the only qualifying related-customer receipt",
                "narrowed": f"Receipt {number} scored clearly above the other qualifying receipts",
            }.get(rule, f"Receipt {number} matched")
        if released_own is not None:
            text += f"; the earlier reservation on receipt {released_own} was released"
        return text + "."


ROLE = consumer_role(MatchReceiptRunner, "match-receipt")
build = ROLE.build
