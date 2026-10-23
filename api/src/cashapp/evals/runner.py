"""Run the selected suites and write the report.

A live extraction run spends real money (two Opus calls and a Cohere call per case, times the
runs), so it is refused before settings are read or any client is built unless the caller
confirmed the spend. The matching and auto-fix suites call no model and never need the flag.
"""

from collections.abc import Awaitable, Callable

import cashapp
from cashapp.domain.adjudication import ADJUDICATION_SCHEMA_VERSION
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.extraction import SCHEMA_VERSION
from cashapp.domain.llm_usage import UsageEntry
from cashapp.evals.config import eval_snapshot
from cashapp.evals.gold import load_gold
from cashapp.evals.models import (
    AutofixSuiteReport,
    EvalReport,
    ExtractionSuiteReport,
    MatchingSuiteReport,
)
from cashapp.evals.options import EvalOptions, Suite, ordered
from cashapp.evals.prior import PriorUnavailable, load_prior
from cashapp.evals.report import write_report
from cashapp.evals.suites.autofix import not_evaluated as autofix_not_evaluated
from cashapp.evals.suites.autofix import run_autofix_suite
from cashapp.evals.suites.extraction import not_evaluated as extraction_not_evaluated
from cashapp.evals.suites.extraction import run_extraction_suite
from cashapp.evals.suites.matching import not_evaluated as matching_not_evaluated
from cashapp.evals.suites.matching import run_matching_suite
from cashapp.evals.usage import EvalUsageRecorder, meter_clients, summarise_cost
from cashapp.integrations.llm.base import LlmClients
from cashapp.integrations.llm.fake import ReplayLlmClient
from cashapp.services.config import ConfigSnapshot
from cashapp.stations.adjudicate.prompts import PROMPT_VERSION as ADJUDICATE_PROMPT_VERSION
from cashapp.stations.extract.prompts import PROMPT_VERSION as EXTRACT_PROMPT_VERSION

__all__ = ["LlmFactory", "SpendNotConfirmed", "run_evals", "spend_refusal"]

type LlmFactory = Callable[[ConfigSnapshot], Awaitable[LlmClients]]


class SpendNotConfirmed(Exception):  # noqa: N818 - pinned name
    """A live extraction run was requested without ``--confirm-spend``."""


def spend_refusal(options: EvalOptions) -> str:
    cases = len(list(options.gold_dir.glob("*.json"))) if options.gold_dir.is_dir() else 0
    if options.limit is not None:
        cases = min(cases, options.limit)
    return (
        "refusing: a live extraction run calls Opus x2 + Cohere per case "
        f"({cases} cases x {options.runs} runs); re-run with --confirm-spend or --replay"
    )


class _DiscardRecorder:
    """The factory's own metering is not used: the harness meters every role itself."""

    async def record(self, entry: UsageEntry) -> None:
        return None


async def _live_clients(snapshot: ConfigSnapshot) -> LlmClients:
    # Imported here so a replay run never loads the Anthropic and OCI SDKs.
    from cashapp.integrations.llm.factory import build_llm_clients
    from cashapp.services.runtime_settings import start_runtime_settings
    from cashapp.settings import aload_settings

    runtime = await start_runtime_settings(await aload_settings())
    return build_llm_clients(runtime, snapshot, recorder=_DiscardRecorder())


def _replay_clients(options: EvalOptions) -> LlmClients:
    def client() -> ReplayLlmClient:
        return ReplayLlmClient(recordings_dir=options.recordings_dir)

    return LlmClients(
        reader_a=client(), reader_b=client(), adjudicator=client(), workhorse=client()
    )


async def run_evals(
    options: EvalOptions,
    *,
    llm_factory: LlmFactory | None = None,
    clock: Clock | None = None,
) -> EvalReport:
    """Run the suites in ``options`` and write ``report.md`` and ``report.json`` to its out dir.

    Raises ``SpendNotConfirmed`` before anything is loaded or built when a paid run was not
    confirmed. A suite that fails is reported ``not_evaluated`` with the exception type, never
    a partial score; the other suites still run.
    """
    if options.needs_models and not options.confirm_spend:
        raise SpendNotConfirmed(spend_refusal(options))

    the_clock = clock if clock is not None else SystemClock()
    started = the_clock.now()
    snapshot = eval_snapshot(options.config_overrides)  # refuses a bad override up front
    options.out_dir.mkdir(parents=True, exist_ok=False)

    recorder = EvalUsageRecorder()
    extraction: ExtractionSuiteReport | None = None
    matching: MatchingSuiteReport | None = None
    autofix: AutofixSuiteReport | None = None

    if Suite.EXTRACTION in options.suites:
        try:
            cases = load_gold(options.gold_dir)
            if options.limit is not None:
                cases = cases[: options.limit]
            if options.replay:
                clients = _replay_clients(options)
            else:
                factory = llm_factory if llm_factory is not None else _live_clients
                clients = await factory(snapshot)
            metered = meter_clients(clients.with_models(snapshot.models()), recorder)
            extraction = await run_extraction_suite(
                cases,
                metered,
                snapshot,
                runs=options.runs,
                artifacts_dir=options.artifacts_dir,
                outputs_dir=None if options.replay else options.out_dir / "outputs",
                empty_reason=f"no gold cases found in {options.gold_dir}",
            )
        except Exception as exc:
            extraction = extraction_not_evaluated(
                f"the extraction suite failed ({type(exc).__name__})", options.runs
            )

    if Suite.MATCHING in options.suites or Suite.AUTOFIX in options.suites:
        try:
            prior = load_prior(options.prior_dir)
        except PriorUnavailable as exc:
            if Suite.MATCHING in options.suites:
                matching = matching_not_evaluated(str(exc))
            if Suite.AUTOFIX in options.suites:
                autofix = autofix_not_evaluated(str(exc))
        else:
            if Suite.MATCHING in options.suites:
                try:
                    matching = await run_matching_suite(prior, snapshot, limit=options.limit)
                except Exception as exc:
                    matching = matching_not_evaluated(
                        f"the matching suite failed ({type(exc).__name__})"
                    )
            if Suite.AUTOFIX in options.suites:
                try:
                    autofix = await run_autofix_suite(prior, snapshot, limit=options.limit)
                except Exception as exc:
                    autofix = autofix_not_evaluated(
                        f"the auto-fix suite failed ({type(exc).__name__})"
                    )

    finished = the_clock.now()
    models = snapshot.models()
    report = EvalReport(
        run_id=started.strftime("%Y%m%dT%H%M%SZ"),
        started_at=started,
        finished_at=finished,
        cashapp_version=cashapp.__version__,
        suites=ordered(options.suites),
        limit=options.limit,
        runs=options.runs,
        replay=options.replay,
        config_overrides=dict(options.config_overrides),
        models={
            "reader_a": models.reader_a.model_id,
            "reader_b": models.reader_b.model_id,
            "adjudicator": models.adjudicator.model_id,
            "workhorse": models.workhorse.model_id,
        },
        prompt_versions={
            "extract_prompt": EXTRACT_PROMPT_VERSION,
            "adjudicate_prompt": ADJUDICATE_PROMPT_VERSION,
            "extraction_schema": SCHEMA_VERSION,
            "adjudication_schema": ADJUDICATION_SCHEMA_VERSION,
        },
        cost=summarise_cost(recorder, mode="replay" if options.replay else "live"),
        extraction=extraction,
        matching=matching,
        autofix=autofix,
    )
    write_report(report, options.out_dir)
    return report
