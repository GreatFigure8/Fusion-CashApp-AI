"""Command line: `python -m cashapp.tools.testdata --pod dev --scenario split_payment --tag T001`.

A thin shell over the plain modules. Settings are loaded only here, and only for a real run:
`--dry-run` loads no settings and builds no Fusion client.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from cashapp.integrations.fusion import FusionClient, FusionClientFactory
from cashapp.settings import FusionPodSettings, FusionTestDataSettings, Settings, load_settings
from cashapp.tools.testdata.cleanup import cleanup, render_cleanup_steps
from cashapp.tools.testdata.fixtures import write_fixtures, write_manifest
from cashapp.tools.testdata.generator import GenerationError, generate
from cashapp.tools.testdata.models import ScenarioName, ScenarioParams, ScenarioPlan
from cashapp.tools.testdata.safety import ProductionPodRefused, assert_non_production
from cashapp.tools.testdata.scenarios import build_plan
from cashapp.tools.testdata.tagging import validate_tag

DEFAULT_OUT = Path("tests/fixtures/testdata")  # relative to api/
EXIT_FAILED = 1
EXIT_REFUSED = 2

app = typer.Typer(add_completion=False, help="Generate tagged Fusion test data for hard cases.")


def _fail(message: str, code: int) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code=code)


def _parse_date(value: str | None) -> date:
    if value is None:
        return datetime.now(UTC).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("use YYYY-MM-DD", param_hint="--as-of") from exc


def _params(currency: str, lines: int, seed: int, as_of: date) -> ScenarioParams:
    try:
        return ScenarioParams(currency=currency.upper(), lines=lines, seed=seed, as_of=as_of)
    except ValidationError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _plan_for(
    scenario: ScenarioName, params: ScenarioParams, tag: str, customer: str
) -> ScenarioPlan:
    return build_plan(scenario, params, tag=tag, customer_account=customer)


async def _generate_run(
    plan: ScenarioPlan,
    fusion: FusionClient,
    *,
    tag: str,
    defaults: FusionTestDataSettings,
    bill_to_site: str | None,
    out: Path,
    drop_folder: Path | None,
    guard: _Guard,
) -> int:
    try:
        try:
            data = await generate(
                plan, fusion, tag=tag, defaults=defaults, bill_to_site=bill_to_site, guard=guard
            )
        except GenerationError as exc:
            manifest = write_manifest(exc.partial, out)
            typer.echo(f"generation failed: {exc}", err=True)
            typer.echo(f"partial manifest: {manifest}", err=True)
            return EXIT_FAILED
        manifest = write_manifest(data, out)
        paths = write_fixtures(plan, out, drop_folder=drop_folder)
        typer.echo(f"scenario {plan.scenario.value} tag {tag} on pod {data.pod_name}")
        for record in data.records:
            typer.echo(f"  {record.kind} {record.number} id={record.fusion_id}")
        typer.echo(f"manifest: {manifest}")
        typer.echo(f"remittance: {paths.remittance_csv}")
        return 0
    finally:
        await fusion.aclose()


async def _cleanup_run(fusion: FusionClient, *, tag: str, out: Path, guard: _Guard) -> int:
    try:
        report = await cleanup(tag, fusion, manifest_dir=out, guard=guard)
        typer.echo(render_cleanup_steps(report))
        return 0
    finally:
        await fusion.aclose()


class _Guard:
    """The production-pod check as a zero-argument callable (the `guard` hook)."""

    def __init__(
        self,
        pod_name: str,
        pod: FusionPodSettings,
        settings: Settings,
        extra_hosts: list[str],
        *,
        require_testdata: bool,
    ) -> None:
        self._args = (pod_name, pod, settings, extra_hosts, require_testdata)

    def __call__(self) -> None:
        pod_name, pod, settings, extra_hosts, require_testdata = self._args
        assert_non_production(
            pod_name,
            pod,
            all_pods=settings.fusion.pods,
            extra_production_hosts=extra_hosts,
            require_testdata=require_testdata,
        )


@app.command()
def run(
    scenario: Annotated[
        ScenarioName, typer.Option("--scenario", help="Preset to generate.")
    ] = ScenarioName.ONE_TO_ONE,
    tag: Annotated[str, typer.Option("--tag", help="1 to 8 letters or digits.")] = "",
    pod: Annotated[
        str | None, typer.Option("--pod", help="Fusion pod (default: configured).")
    ] = None,
    lines: Annotated[int, typer.Option("--lines", help="Invoice count (1 to 50).")] = 3,
    currency: Annotated[str, typer.Option("--currency", help="ISO currency code.")] = "USD",
    seed: Annotated[int, typer.Option("--seed", help="Amounts seed.")] = 0,
    as_of: Annotated[str | None, typer.Option("--as-of", help="Payment date, YYYY-MM-DD.")] = None,
    customer: Annotated[
        str | None, typer.Option("--customer", help="Customer account number (not for dry runs).")
    ] = None,
    bill_to_site: Annotated[str | None, typer.Option("--bill-to-site")] = None,
    out: Annotated[
        Path, typer.Option("--out", help="Fixture and manifest directory.")
    ] = DEFAULT_OUT,
    drop_folder: Annotated[
        Path | None, typer.Option("--drop-folder", help="Also copy the remittance CSV here.")
    ] = None,
    production_host: Annotated[
        list[str] | None,
        typer.Option("--production-host", help="Extra host to refuse (repeatable)."),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the plan; call nothing.")
    ] = False,
    do_cleanup: Annotated[
        bool, typer.Option("--cleanup", help="List the tag's records and print removal steps.")
    ] = False,
) -> None:
    try:
        tag = validate_tag(tag)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--tag") from exc
    if dry_run and do_cleanup:
        raise _fail("--dry-run and --cleanup cannot be combined", EXIT_REFUSED)
    extra_hosts = list(production_host or [])

    if dry_run:
        params = _params(currency, lines, seed, _parse_date(as_of))
        plan = _plan_for(scenario, params, tag, customer or f"CATD-{tag}-CUST")
        typer.echo(plan.model_dump_json(indent=2))
        paths = write_fixtures(plan, out, drop_folder=drop_folder)
        typer.echo(f"fixtures written to {paths.plan.parent}", err=True)
        return

    settings = load_settings()
    pod_name = (pod or settings.fusion.default_pod).lower()
    pod_settings = settings.fusion.pods.get(pod_name)
    if pod_settings is None:
        raise _fail(
            f"unknown pod '{pod_name}'; known pods: {', '.join(sorted(settings.fusion.pods))}",
            EXIT_REFUSED,
        )
    guard = _Guard(pod_name, pod_settings, settings, extra_hosts, require_testdata=not do_cleanup)
    try:
        guard()
    except ProductionPodRefused as exc:
        raise _fail(str(exc), EXIT_REFUSED) from exc

    if do_cleanup:
        fusion = FusionClientFactory(settings).for_pod(pod_name)
        raise typer.Exit(code=asyncio.run(_cleanup_run(fusion, tag=tag, out=out, guard=guard)))

    defaults = pod_settings.testdata
    if defaults is None:
        raise _fail(f"pod '{pod_name}' has no testdata block configured", EXIT_REFUSED)
    if customer is None:
        raise typer.BadParameter("required for a real run", param_hint="--customer")
    params = _params(currency, lines, seed, _parse_date(as_of))
    plan = _plan_for(scenario, params, tag, customer)
    fusion = FusionClientFactory(settings).for_pod(pod_name)
    code = asyncio.run(
        _generate_run(
            plan,
            fusion,
            tag=tag,
            defaults=defaults,
            bill_to_site=bill_to_site,
            out=out,
            drop_folder=drop_folder,
            guard=guard,
        )
    )
    raise typer.Exit(code=code)
