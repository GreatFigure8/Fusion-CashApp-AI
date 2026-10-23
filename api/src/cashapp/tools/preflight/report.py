"""Preflight result types and the plain-text table the CLI prints."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["CheckResult", "CheckStatus", "PreflightReport", "render_table"]


class CheckStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - a status label, not a password
    FAIL = "FAIL"
    INFO = "INFO"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class PreflightReport:
    pod_name: str
    env: str
    results: tuple[CheckResult, ...]

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status is CheckStatus.FAIL)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def result(self, name: str) -> CheckResult:
        for r in self.results:
            if r.name == name:
                return r
        raise KeyError(name)


def render_table(report: PreflightReport) -> str:
    """Fixed-width plain text: `CHECK | STATUS | DETAIL`, a header line and a RESULT footer."""
    name_w = max([len("CHECK"), *(len(r.name) for r in report.results)])
    status_w = len("STATUS")
    lines = [
        f"Fusion preflight: pod={report.pod_name} env={report.env}",
        f"{'CHECK':<{name_w}} | {'STATUS':<{status_w}} | DETAIL",
        f"{'-' * name_w}-+-{'-' * status_w}-+-{'-' * 6}",
    ]
    lines.extend(
        f"{r.name:<{name_w}} | {r.status.value:<{status_w}} | {r.detail}" for r in report.results
    )
    verdict = "PASS" if report.ok else "FAIL"
    lines.append(f"RESULT: {verdict} ({report.failed} failed)")
    return "\n".join(lines)
