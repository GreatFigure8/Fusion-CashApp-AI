"""API contracts for the LLM usage ledger. Separate from the ORM and the service dataclasses."""

from datetime import date, datetime

from pydantic import BaseModel

from cashapp.domain.llm_usage import LlmRole, UsageOutcome, UsdStr
from cashapp.services.llm_usage.reporting import CohereUtilisation, DailyUsage, UsageCall


class DailyUsageOut(BaseModel):
    day: date
    station: str | None
    model: str | None
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: UsdStr
    unpriced_calls: int

    @classmethod
    def of(cls, row: DailyUsage) -> "DailyUsageOut":
        return cls(
            day=row.day,
            station=row.station,
            model=row.model,
            calls=row.calls,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cost_usd=row.cost_usd,
            unpriced_calls=row.unpriced_calls,
        )


class UsageCallOut(BaseModel):
    id: int
    created_at: datetime
    station: str
    purpose: str
    role: LlmRole
    provider: str
    model_id: str
    prompt_version: str | None
    schema_version: str | None
    effort: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    cost_usd: UsdStr | None
    outcome: UsageOutcome
    error_code: str | None

    @classmethod
    def of(cls, row: UsageCall) -> "UsageCallOut":
        return cls(
            id=row.id,
            created_at=row.created_at,
            station=row.station,
            purpose=row.purpose,
            role=row.role,
            provider=row.provider,
            model_id=row.model_id,
            prompt_version=row.prompt_version,
            schema_version=row.schema_version,
            effort=row.effort,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            latency_ms=row.latency_ms,
            cost_usd=row.cost_usd,
            outcome=row.outcome,
            error_code=row.error_code,
        )


class CohereUtilisationOut(BaseModel):
    window_minutes: int
    busy_seconds: float
    calls: int
    utilisation_pct: float
    cluster_utilisation_pct: float | None
    best_pct: float

    @classmethod
    def of(cls, row: CohereUtilisation) -> "CohereUtilisationOut":
        return cls(
            window_minutes=row.window_minutes,
            busy_seconds=row.busy_seconds,
            calls=row.calls,
            utilisation_pct=row.utilisation_pct,
            cluster_utilisation_pct=row.cluster_utilisation_pct,
            best_pct=row.best_pct,
        )
