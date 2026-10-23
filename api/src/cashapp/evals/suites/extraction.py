"""The extraction suite: both readers and the adjudicator against the gold set.

The station code is not driven through its work-item runners (those need a database, artifact
rows and an outbox). Everything that decides what the models see and what is kept is reused: the
content loader and limiter, the reader and adjudicator request builders, the models, effort and
timeouts from the configuration, the single-reader rule and the grounding check. What the stations
send, the eval sends.
"""

import asyncio
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from cashapp.domain.adjudication import (
    ADJUDICATION_SCHEMA_VERSION,
    AdjudicationResult,
    AdjudicatorDecision,
    check_grounding,
    single_reader_result,
)
from cashapp.domain.extraction import SCHEMA_VERSION, ReaderSlot, RemittanceExtraction
from cashapp.evals.gold import GoldCase
from cashapp.evals.models import (
    CaseVariant,
    ExtractionCaseResult,
    ExtractionSuiteReport,
    SuiteStatus,
    VariantName,
)
from cashapp.evals.scoring import aggregate_variant, score_fee_lines, score_fields, score_lines
from cashapp.integrations.llm.base import (
    LlmClient,
    LlmClients,
    LlmError,
    LlmRequest,
    LlmResult,
    parts_digest,
)
from cashapp.integrations.llm.content import (
    ArtifactPartRef,
    FittedParts,
    fit_parts,
    load_content_parts,
)
from cashapp.integrations.llm.fake import Recording
from cashapp.integrations.storage.base import ObjectNotFound
from cashapp.integrations.storage.keys import part_key
from cashapp.integrations.storage.local import LocalFolderObjectStore
from cashapp.services.config import ConfigSnapshot
from cashapp.stations.adjudicate.prompts import build_adjudicator_request
from cashapp.stations.extract.prompts import build_reader_request

__all__ = ["load_case_parts", "not_evaluated", "run_extraction_suite", "save_recording"]

_VARIANTS: Final[tuple[VariantName, ...]] = ("reader_a", "reader_b", "adjudicated")
_EXTENSIONS: Final[dict[str, tuple[str, str]]] = {
    ".txt": ("TEXT", "text/plain"),
    ".csv": ("TABLE", "text/csv"),
    ".pdf": ("PDF", "application/pdf"),
    ".png": ("IMAGE", "image/png"),
    ".jpg": ("IMAGE", "image/jpeg"),
    ".jpeg": ("IMAGE", "image/jpeg"),
    ".docx": (
        "DOCX",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
}
_FAILED: Final = "EXTRACTION_FAILED"


@dataclass(slots=True)
class _Reading:
    """One reader's call: the extraction if it gave one, otherwise why not."""

    extraction: RemittanceExtraction | None
    error_code: str | None
    request: LlmRequest
    result: LlmResult[RemittanceExtraction] | None = None


@dataclass(slots=True)
class _Adjudication:
    result: AdjudicationResult | None
    error_code: str | None
    violations: list[str]
    missing_reader: Literal["A", "B"] | None = None


def save_recording(
    path: Path,
    request: LlmRequest,
    schema_name: str,
    schema_version: str,
    result: LlmResult[RemittanceExtraction] | LlmResult[AdjudicatorDecision],
) -> None:
    """Write one live call in s08's recording shape, ready to promote into the replay set."""
    output = result.output
    record = Recording(
        purpose=request.purpose,
        parts_sha256=parts_digest(request.parts),
        schema=f"{schema_name}@{schema_version}",
        result={
            "output": output.model_dump(mode="json") if output is not None else None,
            "refused": result.refused,
            "stop_reason": result.stop_reason,
            "usage": {
                "model_id": result.usage.model_id,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "latency_ms": result.usage.latency_ms,
            },
            "response_id": result.response_id,
        },
        verified_against_live=True,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_json(), indent=2, sort_keys=True), encoding="utf-8")


async def _read(client: LlmClient, request: LlmRequest) -> _Reading:
    try:
        result = await asyncio.wait_for(
            client.parse(request, RemittanceExtraction), timeout=request.timeout_s
        )
    except TimeoutError:
        return _Reading(None, "LLM_TRANSIENT", request)
    except LlmError as exc:
        return _Reading(None, exc.code.value, request)
    except Exception:  # a client bug must not end the run; the code says what happened
        return _Reading(None, _FAILED, request)
    if result.refused or result.output is None:
        return _Reading(None, "LLM_REFUSAL", request, result)
    return _Reading(result.output, None, request, result)


async def _adjudicate(
    clients: LlmClients,
    config: ConfigSnapshot,
    a: _Reading,
    b: _Reading,
    save_to: Path | None,
) -> _Adjudication:
    reading_a, reading_b = a.extraction, b.extraction
    if reading_a is not None and reading_b is not None:
        role = config.models().adjudicator
        request = build_adjudicator_request(reading_a, reading_b, role=role, work_item_id=0)
        if fit_parts(request.parts).dropped_part_nos:
            return _Adjudication(None, _FAILED, [])
        try:
            llm_result = await asyncio.wait_for(
                clients.adjudicator.parse(request, AdjudicatorDecision), timeout=request.timeout_s
            )
        except TimeoutError:
            return _Adjudication(None, "LLM_TRANSIENT", [])
        except LlmError as exc:
            return _Adjudication(None, exc.code.value, [])
        except Exception:
            return _Adjudication(None, _FAILED, [])
        if save_to is not None:
            save_recording(
                save_to, request, "AdjudicatorDecision", ADJUDICATION_SCHEMA_VERSION, llm_result
            )
        if llm_result.refused or llm_result.output is None:
            return _Adjudication(None, "LLM_REFUSAL", [])
        result = AdjudicationResult.from_decision(llm_result.output)
        return _Adjudication(result, None, check_grounding(result, reading_a, reading_b))
    if reading_a is not None:
        return _Adjudication(single_reader_result(reading_a, ReaderSlot.A), None, [], "B")
    if reading_b is not None:
        return _Adjudication(single_reader_result(reading_b, ReaderSlot.B), None, [], "A")
    return _Adjudication(None, _FAILED, [])


def _variant(
    case: GoldCase, extraction: RemittanceExtraction | None, error_code: str | None
) -> CaseVariant:
    expected = case.expected
    return CaseVariant(
        fields=score_fields(expected, extraction),
        lines=score_lines(expected.lines, extraction),
        fee_lines_ok=score_fee_lines(expected.lines, extraction),
        error_code=error_code if extraction is None else None,
    )


async def load_case_parts(case: GoldCase, artifacts_dir: Path, root: Path) -> FittedParts | None:
    """Stage the artifact in a canonical-layout store and load it as the extract station does."""
    name = case.artifact
    suffix = Path(name).suffix.lower()
    if Path(name).name != name or suffix not in _EXTENSIONS:
        return None
    try:
        data = (artifacts_dir / name).read_bytes()
    except OSError:
        return None
    kind, media_type = _EXTENSIONS[suffix]
    store = LocalFolderObjectStore(root)
    key = part_key(hashlib.sha256(data).hexdigest(), 1)
    await store.put(key, data, media_type, {})
    ref = ArtifactPartRef(part_no=1, kind=kind, media_type=media_type, object_key=key)
    try:
        content = await load_content_parts([ref], store)
    except (LlmError, ObjectNotFound):
        return None
    fitted = fit_parts(content, part_nos=[1])
    return fitted if fitted.parts and not fitted.dropped_part_nos else None


def _failed_case(case: GoldCase, run: int) -> ExtractionCaseResult:
    return ExtractionCaseResult(
        case_id=case.case_id,
        run=run,
        variants={name: _variant(case, None, _FAILED) for name in _VARIANTS},
        missing_reader=None,
        grounding_violations=[],
        disagreements=0,
        adjudication_confidence=None,
    )


async def _run_once(
    case: GoldCase,
    run: int,
    parts: FittedParts,
    clients: LlmClients,
    config: ConfigSnapshot,
    outputs_dir: Path | None,
) -> ExtractionCaseResult:
    models = config.models()
    request_a = build_reader_request(
        parts.parts,
        role=models.reader_a,
        effort=models.reader_a.effort,
        slot=ReaderSlot.A,
        work_item_id=0,
    )
    # Cohere has no effort setting: the station passes none for reader B.
    request_b = build_reader_request(
        parts.parts, role=models.reader_b, effort=None, slot=ReaderSlot.B, work_item_id=0
    )
    a, b = await asyncio.gather(
        _read(clients.reader_a, request_a), _read(clients.reader_b, request_b)
    )
    case_dir = outputs_dir / case.case_id / str(run) if outputs_dir is not None else None
    if case_dir is not None:
        for reading in (a, b):
            if reading.result is not None:
                save_recording(
                    case_dir / f"{reading.request.purpose}.json",
                    reading.request,
                    "RemittanceExtraction",
                    SCHEMA_VERSION,
                    reading.result,
                )
    adjudication = await _adjudicate(
        clients,
        config,
        a,
        b,
        case_dir / "adjudicate.adjudicator.json" if case_dir is not None else None,
    )
    final = adjudication.result.final if adjudication.result is not None else None
    return ExtractionCaseResult(
        case_id=case.case_id,
        run=run,
        variants={
            "reader_a": _variant(case, a.extraction, a.error_code),
            "reader_b": _variant(case, b.extraction, b.error_code),
            "adjudicated": _variant(case, final, adjudication.error_code),
        },
        missing_reader=adjudication.missing_reader,
        grounding_violations=adjudication.violations,
        disagreements=len(adjudication.result.disagreements) if adjudication.result else 0,
        adjudication_confidence=adjudication.result.confidence if adjudication.result else None,
    )


def not_evaluated(reason: str, runs: int) -> ExtractionSuiteReport:
    """An empty report that says nothing was measured."""
    return ExtractionSuiteReport(
        status=SuiteStatus.NOT_EVALUATED,
        reason=reason,
        cases=0,
        runs=runs,
        by_variant={},
        per_case=[],
    )


async def run_extraction_suite(
    cases: list[GoldCase],
    clients: LlmClients,
    config: ConfigSnapshot,
    *,
    runs: int,
    artifacts_dir: Path,
    outputs_dir: Path | None = None,
    empty_reason: str = "no gold cases found",
) -> ExtractionSuiteReport:
    """Score reader A, reader B and the adjudicated result of every case, ``runs`` times each.

    No cases means ``not_evaluated``: an empty set is never reported as a clean score.
    """
    if not cases:
        return not_evaluated(empty_reason, runs)
    per_case: list[ExtractionCaseResult] = []
    with tempfile.TemporaryDirectory(prefix="cashapp-evals-") as staging:
        root = Path(staging)
        for case in cases:
            parts = await load_case_parts(case, artifacts_dir, root)
            for run in range(1, runs + 1):
                if parts is None:
                    per_case.append(_failed_case(case, run))
                else:
                    per_case.append(await _run_once(case, run, parts, clients, config, outputs_dir))
    by_variant = {
        name: aggregate_variant([entry.variants[name] for entry in per_case]) for name in _VARIANTS
    }
    return ExtractionSuiteReport(
        status=SuiteStatus.EVALUATED,
        reason=None,
        cases=len(cases),
        runs=runs,
        by_variant=by_variant,
        per_case=per_case,
    )
