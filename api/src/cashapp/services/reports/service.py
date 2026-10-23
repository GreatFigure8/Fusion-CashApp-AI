"""The report service: read, generate and email the daily summary, and run the cutover generation.

Nothing here touches ``Request``/``Response``. The caller owns the commit, with two exceptions that
exist so an audit row is never lost: a failed email commits its NOTIFICATION_LOG row before the
error is raised, and the cutover run commits its own transactions.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, datetime, timedelta
from typing import Final

from sqlalchemy.exc import IntegrityError

from cashapp.data.models.report_run import ReportRun
from cashapp.data.repositories.artifacts import is_unique_violation
from cashapp.data.repositories.reports import ReportRunRepository
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.principal import Principal
from cashapp.domain.reports import GENERATED_BY_CUTOVER, GENERATED_BY_USER_PREFIX, ReportKind
from cashapp.domain.work_item import SYSTEM_ACTOR_NAME
from cashapp.services.config import ConfigSnapshot
from cashapp.services.notifications.channel import ChannelSendError
from cashapp.services.notifications.reports import send_report_email
from cashapp.services.reports.daily_summary import daily_summary
from cashapp.services.reports.export import daily_summary_file
from cashapp.services.reports.models import DailySummary, ReportRunInfo

logger = logging.getLogger(__name__)

ReportSender = Callable[..., Awaitable[None]]  # send_report_email's signature

EMAIL_KIND: Final = "daily_summary"


class NoRecipients(Exception):  # noqa: N818 - pinned name
    """No recipients were passed and none are configured."""


class ReportEmailFailed(Exception):  # noqa: N818 - pinned name
    """The email channel refused the message. ``reason`` is the channel's reason class only."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class FutureReportDate(ValueError):  # noqa: N818 - pinned name
    """A report was asked for a day that has not happened yet."""


def run_info(row: ReportRun) -> ReportRunInfo:
    return ReportRunInfo(
        id=row.id,
        kind=row.kind,
        report_date=row.report_date,
        generated_at=row.generated_at,
        generated_by=row.generated_by,
        generated_by_name=row.generated_by_name,
        emailed_to=tuple(row.emailed_to or ()),
        emailed_at=row.emailed_at,
    )


def configured_recipients(config: ConfigSnapshot) -> tuple[str, ...]:
    return config.notifications().recipients.get(EMAIL_KIND, {}).get("email", ())


def _env_label() -> str:
    from cashapp.settings import get_settings

    return get_settings().env.upper()


def _subject(env: str, day: date) -> str:
    return f"[CashApp {env}] Daily summary {day.day} {day:%b %Y}"


def _body(summary: DailySummary) -> str:
    """Counts and per-currency totals only: no payer names in mail."""
    pct = "n/a" if summary.auto_applied_pct is None else f"{summary.auto_applied_pct}%"
    lines = [
        f"Daily summary for {summary.day.isoformat()} (UTC)",
        "",
        f"Items in: {summary.items_in}",
        f"Completed: {summary.completed}",
        f"Auto-applied: {summary.auto_applied} ({pct})",
        f"Escalations: {summary.escalations}",
        "",
        "Amount applied:",
    ]
    if summary.applied_by_currency:
        lines += [f"  {row.currency} {row.amount:.2f}" for row in summary.applied_by_currency]
    else:
        lines.append("  none")
    lines += ["", "Failures by error code:"]
    if summary.failures_by_error_code:
        lines += [
            f"  {row.error_code.value}: {row.count}" for row in summary.failures_by_error_code
        ]
    else:
        lines.append("  none")
    lines += ["", "Open items by age:"]
    lines += [f"  {row.label}: {row.count}" for row in summary.aging_buckets]
    lines += ["", "The XLSX and CSV files are attached."]
    return "\n".join(lines)


class ReportService:
    def __init__(
        self, *, clock: Clock | None = None, sender: ReportSender = send_report_email
    ) -> None:
        self._clock: Clock = clock or SystemClock()
        self._sender = sender

    def _check_not_future(self, day: date) -> None:
        if day > self._clock.now().date():
            raise FutureReportDate(f"{day.isoformat()} is in the future")

    async def get_daily(
        self, uow: UnitOfWork, day: date
    ) -> tuple[DailySummary, ReportRunInfo | None]:
        """The stored report when one exists (so an emailed report never drifts), else live."""
        self._check_not_future(day)
        row = await uow.repo(ReportRunRepository).find(ReportKind.DAILY_SUMMARY, day)
        if row is not None:
            return DailySummary.from_payload(row.payload), run_info(row)
        return await daily_summary(uow, day), None

    async def generate_daily(
        self, uow: UnitOfWork, day: date, principal: Principal
    ) -> tuple[DailySummary, ReportRunInfo]:
        """Compute the day and store it, replacing an earlier run of the same day. Flush only."""
        self._check_not_future(day)
        summary = await daily_summary(uow, day)
        by = f"{GENERATED_BY_USER_PREFIX}{principal.subject}"
        row = await self._store(uow, day, summary, by, principal.display_name)
        return summary, run_info(row)

    async def _store(
        self, uow: UnitOfWork, day: date, summary: DailySummary, by: str, by_name: str
    ) -> ReportRun:
        repo = uow.repo(ReportRunRepository)
        now = self._clock.now()
        existing = await repo.find(ReportKind.DAILY_SUMMARY, day)
        if existing is not None:
            return await repo.update(
                existing,
                payload=summary.to_payload(),
                generated_at=now,
                generated_by=by,
                generated_by_name=by_name,
            )
        try:
            return await repo.add(
                ReportRun(
                    kind=ReportKind.DAILY_SUMMARY,
                    report_date=day,
                    generated_at=now,
                    generated_by=by,
                    generated_by_name=by_name,
                    payload=summary.to_payload(),
                )
            )
        except IntegrityError as exc:
            if not is_unique_violation(exc):
                raise
            # Another request stored the same day first: take its row and overwrite it.
            await uow.rollback()
            winner = await repo.find(ReportKind.DAILY_SUMMARY, day)
            if winner is None:
                raise
            return await repo.update(
                winner,
                payload=summary.to_payload(),
                generated_at=now,
                generated_by=by,
                generated_by_name=by_name,
            )

    async def email_daily(
        self,
        uow: UnitOfWork,
        day: date,
        recipients: Sequence[str] | None,
        principal: Principal,
        config: ConfigSnapshot,
    ) -> ReportRunInfo:
        """Email the stored report for ``day`` (generating it first when there is none)."""
        self._check_not_future(day)
        targets = tuple(recipients) if recipients is not None else configured_recipients(config)
        if not targets:
            raise NoRecipients("no recipients were given and none are configured")
        row = await uow.repo(ReportRunRepository).find(ReportKind.DAILY_SUMMARY, day)
        if row is None:
            summary = await daily_summary(uow, day)
            row = await self._store(
                uow,
                day,
                summary,
                f"{GENERATED_BY_USER_PREFIX}{principal.subject}",
                principal.display_name,
            )
        else:
            summary = DailySummary.from_payload(row.payload)
        await self._send(uow, row, summary, targets)
        return run_info(row)

    async def _send(
        self,
        uow: UnitOfWork,
        row: ReportRun,
        summary: DailySummary,
        recipients: Sequence[str],
    ) -> None:
        """Send, then stamp EMAILED_TO/EMAILED_AT; a failed send keeps its log row only."""
        attachments = [daily_summary_file(summary, "xlsx"), daily_summary_file(summary, "csv")]
        try:
            await self._sender(
                recipients,
                _subject(_env_label(), summary.day),
                _body(summary),
                attachments,
                uow=uow,
                kind=EMAIL_KIND,
                clock=self._clock,
            )
        except ChannelSendError as exc:
            # Keep the failed NOTIFICATION_LOG row (and a freshly stored report) for the audit.
            await uow.commit()
            raise ReportEmailFailed(exc.reason) from exc
        if not recipients:
            return  # the sender logged the suppressed send; nothing was emailed
        await uow.repo(ReportRunRepository).update(
            row, emailed_to=list(recipients), emailed_at=self._clock.now()
        )

    async def run_cutover(
        self, uow_factory: UowFactory, now: datetime, config: ConfigSnapshot
    ) -> bool:
        """Generate and email yesterday's report unless a run already exists.

        Returns True when this process generated it. The unique (KIND, REPORT_DATE) constraint
        decides a race between processes: the loser returns False and never emails. The insert
        and the email are separate transactions, so a crash between them leaves the report
        un-emailed (a person can use "Email to list") rather than risking a double send.
        """
        day = now.date() - timedelta(days=1)
        async with uow_factory() as uow:
            if await uow.repo(ReportRunRepository).find(ReportKind.DAILY_SUMMARY, day) is not None:
                return False
            summary = await daily_summary(uow, day)
            try:
                await uow.repo(ReportRunRepository).add(
                    ReportRun(
                        kind=ReportKind.DAILY_SUMMARY,
                        report_date=day,
                        generated_at=now,
                        generated_by=GENERATED_BY_CUTOVER,
                        generated_by_name=SYSTEM_ACTOR_NAME,
                        payload=summary.to_payload(),
                    )
                )
                await uow.commit()
            except IntegrityError as exc:
                if is_unique_violation(exc):
                    return False
                raise

        recipients = configured_recipients(config)
        async with uow_factory() as uow:
            row = await uow.repo(ReportRunRepository).find(ReportKind.DAILY_SUMMARY, day)
            if row is None:
                return True
            try:
                await self._send(uow, row, summary, recipients)
            except ReportEmailFailed as exc:
                # The failed log row is already committed; leave EMAILED_AT empty, no resend.
                logger.warning("daily summary email failed: reason=%s", exc.reason)
                return True
            await uow.commit()
        return True
