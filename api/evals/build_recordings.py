"""Rebuild the synthetic replay recordings under ``api/evals/recordings/``.

    uv run python evals/build_recordings.py

Each gold case gets three recordings (reader A, reader B, adjudicator), keyed the way
``ReplayLlmClient`` keys them: by purpose and by a digest of the exact content parts a station
would send. The outputs are written by hand below, with deliberate reader mistakes so the replay
metrics are not trivially 100%. They are marked ``verified_against_live: false``: they prove the
harness, not model quality. Re-run this after changing an artifact or a gold file. A prompt change
does not invalidate a recording (the digest covers the parts only), so re-record from a live run
instead, as described in ``evals/README.md``.
"""

import asyncio
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from cashapp.domain.adjudication import HEADER_FIELDS, AdjudicatorDecision
from cashapp.domain.extraction import SCHEMA_VERSION, ReaderSlot, RemittanceExtraction
from cashapp.evals.config import eval_snapshot
from cashapp.evals.gold import load_gold
from cashapp.evals.options import default_paths
from cashapp.evals.suites.extraction import load_case_parts
from cashapp.integrations.llm.base import parts_digest
from cashapp.integrations.llm.fake import Recording
from cashapp.stations.adjudicate.prompts import build_adjudicator_request
from cashapp.stations.extract.prompts import build_reader_request

SOURCE = {"part_no": 1, "page": None, "bbox": None, "quote": None}
DOLLAR = "$"


def field(value: Any, confidence: float = 0.95) -> dict[str, Any]:
    return {"value": value, "source": dict(SOURCE), "confidence": confidence}


def line(
    no: int,
    kind: str,
    number: str,
    amount: str | None = None,
    *,
    po_number: str | None = None,
) -> dict[str, Any]:
    return {
        "line_no": no,
        "kind": kind,
        "transaction_number": number,
        "amount_paid": amount,
        "gross_amount": None,
        "discount_claimed": None,
        "deduction": None,
        "po_number": po_number,
        "sales_order": None,
        "ers_reference": None,
        "source": dict(SOURCE),
        "confidence": 0.95,
    }


def date_candidate(value: str, kind: str) -> dict[str, Any]:
    return {"value": value, "kind": kind, "source": dict(SOURCE), "confidence": 0.95}


def reading(
    *,
    payer: str,
    ref: str,
    amount: str,
    currency_raw: str,
    currency: str | None,
    ambiguous: bool = False,
    dates: list[dict[str, Any]],
    payment_date: str,
    lines: list[dict[str, Any]],
    po_refs: list[str] | None = None,
    fees: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "payer_name": field(payer),
        "payer_bank_account": field(None, 0.9),
        "remittance_reference": field(ref),
        "payment_amount": field(amount),
        "currency_raw": field(currency_raw),
        "currency": field(currency),
        "currency_ambiguous": ambiguous,
        "dates": dates,
        "payment_date": field(payment_date),
        "lines": lines,
        "po_refs": po_refs or [],
        "sales_order_refs": [],
        "ers_refs": [],
        "bank_fees": fees or [],
        "notes": None,
    }


def _comparable(name: str, extraction: dict[str, Any]) -> Any:
    value = extraction[name]
    return value["value"] if isinstance(value, dict) and "confidence" in value else value


def decide(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    take_b: frozenset[str] = frozenset(),
    lines_from: str = "A",
) -> dict[str, Any]:
    """The adjudicator's decision: reader A's values except the fields in ``take_b``."""
    final = deepcopy(a)
    choices: list[dict[str, str]] = []
    disagreements: list[dict[str, Any]] = []
    for name in HEADER_FIELDS:
        if name in take_b:
            final[name] = deepcopy(b[name])
        same = _comparable(name, a) == _comparable(name, b)
        source = "both" if same else ("B" if name in take_b else "A")
        choices.append({"field_path": name, "source": source})
        if not same:
            disagreements.append(
                {
                    "field_path": name,
                    "value_a": json.dumps(_comparable(name, a))[:200],
                    "value_b": json.dumps(_comparable(name, b))[:200],
                    "chosen": source,
                    "reason": "synthetic recording: chosen by hand",
                }
            )
    source_lines = a if lines_from == "A" else b
    final["lines"] = deepcopy(source_lines["lines"])
    if a["lines"] != b["lines"]:
        disagreements.append(
            {
                "field_path": "lines",
                "value_a": f"{len(a['lines'])} lines",
                "value_b": f"{len(b['lines'])} lines",
                "chosen": lines_from,
                "reason": "synthetic recording: chosen by hand",
            }
        )
    return {
        "final": final,
        "field_choices": choices,
        "line_choices": [
            {"line_no": row["line_no"], "source": lines_from} for row in final["lines"]
        ],
        "disagreements": disagreements,
        "confidence": 0.9,
    }


def _inv(no: int, number: str, amount: str | None) -> dict[str, Any]:
    return line(no, "INVOICE", number, amount)


def cases() -> dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    out: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}

    # g01: reader B drops the "-1" suffix of the credit memo.
    a = reading(
        payer="Example Payer One",
        ref="REF-G01",
        amount="2350.00",
        currency_raw="USD",
        currency="USD",
        dates=[date_candidate("2026-03-05", "payment")],
        payment_date="2026-03-05",
        lines=[
            _inv(1, "INV-10021", "1500.00"),
            _inv(2, "2598014", "1200.00"),
            line(3, "CREDIT_MEMO", "2598014-1", "-350.00"),
        ],
    )
    b = deepcopy(a)
    b["lines"][2]["transaction_number"] = "2598014"
    out["g01_credit_memo_suffix"] = (a, b, decide(a, b))

    # g02: reader B drops the third invoice.
    a = reading(
        payer="Example Payer Two",
        ref="REF-G02",
        amount="4120.50",
        currency_raw="EUR",
        currency="EUR",
        dates=[date_candidate("2026-03-12", "payment")],
        payment_date="2026-03-12",
        lines=[_inv(1, "INV-20001", None), _inv(2, "INV-20002", None), _inv(3, "INV-20003", None)],
    )
    b = deepcopy(a)
    b["lines"] = b["lines"][:2]
    out["g02_no_amount_lines"] = (a, b, decide(a, b))

    # g03: a bare "$" stays ambiguous; reader B misreads the amount.
    a = reading(
        payer="Example Payer Three",
        ref="REF-G03",
        amount="980.00",
        currency_raw=DOLLAR,
        currency=None,
        ambiguous=True,
        dates=[date_candidate("2026-03-18", "payment")],
        payment_date="2026-03-18",
        lines=[_inv(1, "INV-30007", "980.00")],
    )
    b = deepcopy(a)
    b["payment_amount"]["value"] = "930.00"
    b["lines"][0]["amount_paid"] = "930.00"
    out["g03_dollar_ambiguous"] = (a, b, decide(a, b))

    # g04: reader A picks the deposit date as the payment date; reader B picks the value date.
    a = reading(
        payer="Example Payer Four",
        ref="REF-G04",
        amount="760.00",
        currency_raw="GBP",
        currency="GBP",
        dates=[
            date_candidate("2026-02-20", "issue"),
            date_candidate("2026-03-02", "payment"),
            date_candidate("2026-03-03", "deposit"),
        ],
        payment_date="2026-03-03",
        lines=[_inv(1, "INV-40010", "760.00")],
    )
    b = deepcopy(a)
    b["payment_date"]["value"] = "2026-03-02"
    out["g04_multiple_dates"] = (a, b, decide(a, b, take_b=frozenset({"payment_date"})))

    # g05: reader A misses the bank fee line and the fee; reader B finds both.
    a = reading(
        payer="Example Payer Five",
        ref="REF-G05",
        amount="3985.00",
        currency_raw="USD",
        currency="USD",
        dates=[date_candidate("2026-03-20", "payment")],
        payment_date="2026-03-20",
        lines=[_inv(1, "INV-50001", "2000.00"), _inv(2, "INV-50002", "2000.00")],
    )
    b = deepcopy(a)
    b["lines"].append(line(3, "BANK_FEE", "", "15.00"))
    b["bank_fees"] = [{"amount": "15.00", "currency": "USD"}]
    out["g05_bank_fee"] = (a, b, decide(a, b, take_b=frozenset({"bank_fees"}), lines_from="B"))

    # g06: reader A misses the purchase-order references; reader B reads them.
    a = reading(
        payer="Example Payer Six",
        ref="REF-G06",
        amount="125000.00",
        currency_raw="INR",
        currency="INR",
        dates=[date_candidate("2026-03-25", "payment")],
        payment_date="2026-03-25",
        lines=[_inv(1, "INV-60001", "75000.00"), _inv(2, "INV-60002", "50000.00")],
    )
    b = deepcopy(a)
    b["po_refs"] = ["PO-6001", "PO-6002"]
    b["lines"][0]["po_number"] = "PO-6001"
    b["lines"][1]["po_number"] = "PO-6002"
    out["g06_inr_whole_rupee"] = (a, b, decide(a, b, take_b=frozenset({"po_refs"})))
    return out


def recording(
    purpose: str,
    digest: str,
    schema: str,
    output: dict[str, Any],
    model_id: str,
    tokens: tuple[int, int],
) -> Recording:
    return Recording(
        purpose=purpose,
        parts_sha256=digest,
        schema=schema,
        result={
            "output": output,
            "refused": False,
            "stop_reason": "end_turn",
            "usage": {
                "model_id": model_id,
                "input_tokens": tokens[0],
                "output_tokens": tokens[1],
                "latency_ms": 1500,
            },
            "response_id": None,
        },
        verified_against_live=False,
    )


async def build(out_dir: Path) -> list[Path]:
    paths = default_paths()
    snapshot = eval_snapshot()
    models = snapshot.models()
    gold = {case.case_id: case for case in load_gold(paths["gold"])}
    written: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="cashapp-evals-") as staging:
        for case_id, (a_raw, b_raw, decision_raw) in cases().items():
            parts = await load_case_parts(gold[case_id], paths["artifacts"], Path(staging))
            if parts is None:
                raise SystemExit(f"cannot load the artifact of {case_id}")
            a = RemittanceExtraction.model_validate(a_raw)
            b = RemittanceExtraction.model_validate(b_raw)
            decision = AdjudicatorDecision.model_validate(decision_raw)
            request_a = build_reader_request(
                parts.parts,
                role=models.reader_a,
                effort=models.reader_a.effort,
                slot=ReaderSlot.A,
                work_item_id=0,
            )
            request_b = build_reader_request(
                parts.parts, role=models.reader_b, effort=None, slot=ReaderSlot.B, work_item_id=0
            )
            request_j = build_adjudicator_request(a, b, role=models.adjudicator, work_item_id=0)
            entries = [
                recording(
                    request_a.purpose,
                    parts_digest(request_a.parts),
                    f"RemittanceExtraction@{SCHEMA_VERSION}",
                    a.model_dump(mode="json"),
                    models.reader_a.model_id,
                    (1800, 900),
                ),
                recording(
                    request_b.purpose,
                    parts_digest(request_b.parts),
                    f"RemittanceExtraction@{SCHEMA_VERSION}",
                    b.model_dump(mode="json"),
                    models.reader_b.model_id,
                    (1700, 850),
                ),
                recording(
                    request_j.purpose,
                    parts_digest(request_j.parts),
                    "AdjudicatorDecision@1",
                    decision.model_dump(mode="json"),
                    models.adjudicator.model_id,
                    (2600, 700),
                ),
            ]
            for entry in entries:
                path = out_dir / f"{case_id}.{entry.purpose}.json"
                path.write_text(
                    json.dumps(entry.to_json(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                written.append(path)
    return written


if __name__ == "__main__":
    for written_path in asyncio.run(build(default_paths()["recordings"])):
        print(written_path.name)
