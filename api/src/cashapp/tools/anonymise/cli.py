"""Command line: ``python -m cashapp.tools.anonymise``.

Exit codes: 0 done, 2 usage error, 3 path or key guard refused, 4 the output still held an
identifier (nothing was written), 5 the source folder does not match the pinned shape. The CLI
prints counts only: never a source value, a pseudonym mapping or the key. Scanner findings print
a masked excerpt.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated, Final

import typer

from cashapp.tools.anonymise.fixture_format import PriorFixtures
from cashapp.tools.anonymise.keys import KeyFileError, init_key, load_key, synthetic_key
from cashapp.tools.anonymise.repo_guard import (
    PathGuardError,
    ensure_not_inside,
    ensure_outside_repo,
)
from cashapp.tools.anonymise.scan import load_denylist
from cashapp.tools.anonymise.source import SourceFormatError, load_source
from cashapp.tools.anonymise.synthetic import write_synthetic_source
from cashapp.tools.anonymise.transform import anonymise
from cashapp.tools.anonymise.writer import IdentifierFoundError, write_fixtures

DENYLIST_ENV: Final = "CASHAPP_IDENTIFIER_DENYLIST"
EXIT_USAGE: Final = 2
EXIT_GUARD: Final = 3
EXIT_IDENTIFIERS: Final = 4
EXIT_SOURCE: Final = 5

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Anonymise prior build data.")


def _fail(message: str, code: int) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code)


def _summary(fixtures: PriorFixtures, *, synthetic: bool) -> str:
    counts = fixtures.manifest.counts
    return (
        f"messages={counts['messages']} lines={counts['lines']} "
        f"customers={counts['customers']} clusters={counts['clusters']} findings=0 "
        f"failures={counts['failures']} numeric_ids_coerced={counts['numeric_ids_coerced']} "
        f"synthetic={str(synthetic).lower()}"
    )


def _run(
    source: Path,
    key: bytes,
    out: Path,
    denylist: tuple[str, ...],
    *,
    synthetic: bool,
    seed: int | None,
) -> None:
    try:
        bundle = load_source(source)
    except SourceFormatError as exc:
        raise _fail(f"source format error: {exc}", EXIT_SOURCE) from exc
    fixtures = anonymise(bundle, key)
    manifest = fixtures.manifest.model_copy(update={"synthetic": synthetic, "seed": seed})
    fixtures = fixtures.model_copy(update={"manifest": manifest})
    try:
        write_fixtures(fixtures, out, denylist=denylist, synthetic=synthetic)
    except IdentifierFoundError as exc:
        for finding in exc.findings:
            typer.echo(finding.render(), err=True)
        raise _fail(
            f"output scan found {len(exc.findings)} identifier(s); nothing was written",
            EXIT_IDENTIFIERS,
        ) from exc
    typer.echo(_summary(fixtures, synthetic=synthetic))


@app.command()
def main(
    out: Annotated[Path, typer.Option("--out", help="Fixture folder to write.")],
    source: Annotated[
        Path | None, typer.Option("--source", help="Source folder (outside the repo).")
    ] = None,
    key_file: Annotated[
        Path | None, typer.Option("--key-file", help="HMAC key file (outside the repo).")
    ] = None,
    denylist: Annotated[
        Path | None,
        typer.Option("--denylist", envvar=DENYLIST_ENV, help="Denylist file (outside the repo)."),
    ] = None,
    init_key_flag: Annotated[
        bool, typer.Option("--init-key", help="Create the key file if it does not exist.")
    ] = False,
    synthetic: Annotated[
        bool, typer.Option("--synthetic", help="Generate and use a fake source instead.")
    ] = False,
    seed: Annotated[int, typer.Option("--seed", help="Synthetic seed.")] = 43,
    messages: Annotated[int, typer.Option("--messages", help="Synthetic message count.")] = 40,
    source_out: Annotated[
        Path | None, typer.Option("--source-out", help="Where --synthetic writes its source.")
    ] = None,
) -> None:
    if (source is None) == (not synthetic):
        raise _fail("give exactly one of --source or --synthetic", EXIT_USAGE)
    if synthetic and (key_file is not None or init_key_flag):
        raise _fail("--key-file and --init-key are not allowed with --synthetic", EXIT_USAGE)
    if not synthetic and key_file is None:
        raise _fail("--key-file is required with --source", EXIT_USAGE)
    if not synthetic and source_out is not None:
        raise _fail("--source-out is only for --synthetic", EXIT_USAGE)

    try:
        names: tuple[str, ...] = ()
        if denylist is not None:
            names = load_denylist(ensure_outside_repo(denylist, what="denylist file"))
        if synthetic:
            if source_out is not None:
                target = ensure_outside_repo(source_out, what="synthetic source folder")
                ensure_not_inside(out, target, what="--out must not be inside the source folder")
                write_synthetic_source(target, seed=seed, messages=messages)
                _run(target, synthetic_key(seed), out, names, synthetic=True, seed=seed)
            else:
                with tempfile.TemporaryDirectory(prefix="cashapp-synthetic-") as scratch:
                    target = ensure_outside_repo(Path(scratch), what="synthetic source folder")
                    write_synthetic_source(target, seed=seed, messages=messages)
                    _run(target, synthetic_key(seed), out, names, synthetic=True, seed=seed)
            return
        assert source is not None  # noqa: S101 - narrowed by the checks above
        assert key_file is not None  # noqa: S101
        src = ensure_outside_repo(source, what="--source")
        key_path = ensure_outside_repo(key_file, what="--key-file")
        ensure_not_inside(out, src, what="--out must not be inside the source folder")
        if init_key_flag:
            init_key(key_path)
        key = load_key(key_path)
    except PathGuardError as exc:
        raise _fail(f"refused: {exc}", EXIT_GUARD) from exc
    except KeyFileError as exc:
        raise _fail(f"refused: {exc}", EXIT_GUARD) from exc
    _run(src, key, out, names, synthetic=False, seed=None)
