"use client";

import { useState, useTransition } from "react";

import { refreshFlowSummary } from "@/app/(shell)/flow/actions";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorAlert } from "@/components/common/error-alert";
import { KpiCard } from "@/components/common/kpi-card";
import { Money } from "@/components/common/money";
import { BacklogBar } from "@/components/flow/backlog-bar";
import { StageTile } from "@/components/flow/stage-tile";
import { useFlowStream } from "@/components/shell/flow-stream";
import { Badge } from "@/components/ui/badge";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import { minutesSince } from "@/lib/format";
import type { Result } from "@/lib/result";
import { cn } from "@/lib/utils";

type FlowSummary = Schemas["FlowSummaryOut"];

type Local = { summary: FlowSummary | null; error: ApiError | null };

function stamp(summary: FlowSummary): number {
  const parsed = Date.parse(summary.generated_at);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function pollerLine(summary: FlowSummary): string {
  const intake = summary.pollers.find((p) => p.name === "intake-poller");
  const minutes = minutesSince(intake?.last_cycle_at);
  return minutes === null
    ? "The intake poller hasn't run yet."
    : `The intake poller last checked the mailbox ${minutes} ${minutes === 1 ? "minute" : "minutes"} ago.`;
}

function KpiStrip({ summary }: { summary: FlowSummary | null }) {
  const kpis = summary?.kpis;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <KpiCard label="In today" value={kpis?.in_today ?? "—"} loading={!summary} />
      <KpiCard
        label="Auto-applied"
        value={kpis?.auto_applied_pct == null ? "—" : `${kpis.auto_applied_pct.toFixed(1)}%`}
        loading={!summary}
      />
      <KpiCard
        label="Applied"
        loading={!summary}
        value={
          kpis && kpis.applied_by_currency.length > 0 ? (
            <div className="flex flex-col text-base">
              {kpis.applied_by_currency.map((m) => (
                <Money key={m.currency} amount={m.amount} currency={m.currency} />
              ))}
            </div>
          ) : (
            "—"
          )
        }
      />
      <KpiCard label="Needs a person" value={kpis?.needs_person ?? "—"} loading={!summary} />
    </div>
  );
}

/** The live assembly line: KPI strip, backlog progress and one tile per station. */
export function FlowMonitor({
  initial,
  canPauseBacklog,
}: {
  initial: Result<FlowSummary, ApiError>;
  canPauseBacklog: boolean;
}) {
  const live = useFlowStream().summary;
  const [local, setLocal] = useState<Local>(
    initial.ok ? { summary: initial.value, error: null } : { summary: null, error: initial.error },
  );
  const [retrying, startRetry] = useTransition();

  // The newest summary wins, and a fresh one clears the error.
  const liveWins = live !== null && (local.summary === null || stamp(live) >= stamp(local.summary));
  const summary = liveWins ? live : local.summary;
  const error = liveWins ? null : local.error;
  const stale = error !== null && summary !== null;

  const retry = () =>
    startRetry(async () => {
      const result = await refreshFlowSummary();
      setLocal((previous) =>
        result.ok
          ? { summary: result.value, error: null }
          : { summary: previous.summary, error: result.error },
      );
    });

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold tracking-tight">Flow</h1>
        <div className="flex items-center gap-2">
          {stale ? <Badge variant="outline">stale</Badge> : null}
        </div>
      </div>

      {error ? (
        <ErrorAlert
          error={error}
          title="Couldn't load the flow"
          onRetry={retry}
          retrying={retrying}
        />
      ) : null}

      <div className={cn("flex min-w-0 flex-col gap-4", stale && "opacity-60")}>
        <KpiStrip summary={summary} />
        {summary?.backlog.map((batch) => (
          <BacklogBar key={batch.id} batch={batch} canPause={canPauseBacklog} />
        ))}
        {summary && summary.kpis.in_today === 0 ? (
          <EmptyState title="Nothing has arrived yet today." description={pollerLine(summary)} />
        ) : null}
        {summary ? (
          <div
            data-slot="stage-line"
            className="flex flex-col gap-2 md:flex-row md:overflow-x-auto md:pb-2"
          >
            {summary.stages.map((tile) => (
              <StageTile
                key={tile.stage}
                tile={tile}
                cohereUtilisationPct={summary.cohere_utilisation_pct}
              />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
