"""Write the five managed fixture files, only after the output passed the identifier scan.

Everything is written into a sibling temp folder first and scanned (structural patterns plus the
denylist). Only on zero findings are the five managed files moved into ``out`` one by one with
``os.replace``. ``out`` itself is never removed and other files in it are never touched.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cashapp.tools.anonymise.fixture_format import (
    FAILURES_FILE,
    FORMAT_VERSION,
    FUSION_FILE,
    MANAGED_FILES,
    MANIFEST_FILE,
    MESSAGES_FILE,
    README_FILE,
    PriorFixtures,
    to_json_document,
    to_jsonl,
)
from cashapp.tools.anonymise.scan import Finding, scan_paths

REGENERATE_SYNTHETIC = (
    "uv run python -m cashapp.tools.anonymise --synthetic --seed {seed} --out tests/fixtures/prior"
)
REGENERATE_REAL = (
    "uv run python -m cashapp.tools.anonymise --source <dir outside repo> "
    "--out tests/fixtures/prior --key-file <path outside repo>"
)


class IdentifierFoundError(Exception):
    """The output still contains an identifier; nothing was written to ``out``."""

    def __init__(self, findings: Sequence[Finding]) -> None:
        self.findings = tuple(findings)
        super().__init__(f"{len(self.findings)} identifier finding(s) in the output")


@dataclass(frozen=True)
class WriteResult:
    out: Path
    files: tuple[str, ...]


def _readme(fixtures: PriorFixtures, *, synthetic: bool) -> str:
    manifest = fixtures.manifest
    if synthetic:
        origin = f"synthetic source, seed {manifest.seed}"
        command = REGENERATE_SYNTHETIC.format(seed=manifest.seed)
        warning = (
            "These files are generated from fake data so tests and the eval harness can run "
            "before the real data exists. Replace them by running the real command below, "
            "then this first line becomes `synthetic: false`."
        )
    else:
        origin = "real source (anonymised)"
        command = REGENERATE_REAL
        warning = "These files come from the previous build's production day, anonymised."
    return (
        f"synthetic: {'true' if synthetic else 'false'}\n"
        "\n"
        "# Prior-build fixtures\n"
        "\n"
        f"{warning}\n"
        "\n"
        f"- Format version: {FORMAT_VERSION}\n"
        f"- Origin: {origin}\n"
        f"- Key id: {manifest.key_id}\n"
        f"- Regenerate: `{command}`\n"
        "\n"
        "Layout: `day/messages.jsonl` (one extraction plus outcome per line), `day/fusion.json` "
        "(FusionScenario shape), `labelled/failures.jsonl` (AR labels), `manifest.json`.\n"
        "\n"
        "Never commit the HMAC key or the source folder. Keep the denylist file outside the repo "
        "and set `CASHAPP_IDENTIFIER_DENYLIST` in the shell, not in `api/.env`.\n"
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_fixtures(
    fixtures: PriorFixtures,
    out: Path,
    *,
    denylist: Sequence[str],
    synthetic: bool,
) -> WriteResult:
    out = out.resolve()
    manifest = fixtures.manifest.model_copy(update={"synthetic": synthetic})
    fixtures = fixtures.model_copy(update={"manifest": manifest})
    temp = out.parent / f".{out.name}.tmp-{uuid.uuid4().hex}"
    try:
        _write(temp / README_FILE, _readme(fixtures, synthetic=synthetic))
        _write(temp / MANIFEST_FILE, to_json_document(fixtures.manifest.model_dump(mode="json")))
        _write(temp / MESSAGES_FILE, to_jsonl(fixtures.messages))
        _write(temp / FUSION_FILE, to_json_document(fixtures.fusion))
        _write(temp / FAILURES_FILE, to_jsonl(fixtures.failures))
        findings = scan_paths([temp], denylist, base=temp)
        if findings:
            raise IdentifierFoundError(findings)
        for name in MANAGED_FILES:
            destination = out / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp / name, destination)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return WriteResult(out=out, files=MANAGED_FILES)
