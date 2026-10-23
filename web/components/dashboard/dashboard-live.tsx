"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ActivityFeed } from "@/components/dashboard/activity-feed";
import { KpiRow } from "@/components/dashboard/kpi-row";
import { ModelEfficiencyTable } from "@/components/dashboard/model-efficiency-table";
import { StaleBanner } from "@/components/dashboard/stale-banner";
import { useEventStream, type StreamEvent } from "@/hooks/use-event-stream";
import type { Schemas } from "@/lib/api/types";
import {
  ActivityFrameSchema,
  MetricsFrameSchema,
  SummaryFrameSchema,
  type MetricsFrame,
} from "@/lib/metrics/schemas";
import { secondsAgo } from "@/lib/metrics/format";

type Summary = Schemas["SummaryOut"];
type Event = Schemas["ActivityEvent"];

const ACTIVITY_CAP = 50;
const TICK_MS = 1_000;

/**
 * The one client leaf of the dashboard: it holds the live summary and activity, seeded from the
 * server render, and keeps the last good values (marked stale) when the stream fails. The panels
 * that do not change with the stream come in as `children`.
 */
export function DashboardLive({
  initialSummary,
  initialActivity,
  models,
  cohereUtilisationPct,
  window,
  children,
}: {
  initialSummary: Summary;
  initialActivity: readonly Event[];
  models: readonly Schemas["ModelEfficiencyRow"][];
  cohereUtilisationPct: number | null;
  window: string;
  children: ReactNode;
}) {
  const [summary, setSummary] = useState<Summary>(initialSummary);
  const [activity, setActivity] = useState<readonly Event[]>(initialActivity);
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);
  const [now, setNow] = useState<number>(0);
  const [failed, setFailed] = useState(false);

  const onEvent = useCallback((frame: StreamEvent<MetricsFrame>) => {
    setFailed(false);
    setLastEventAt(Date.now());
    if (frame.event === "summary") {
      const parsed = SummaryFrameSchema.safeParse(frame.data);
      if (parsed.success) setSummary(parsed.data as Summary);
      return;
    }
    if (frame.event === "activity") {
      const parsed = ActivityFrameSchema.safeParse(frame.data);
      if (!parsed.success) return;
      const event: Event = parsed.data;
      setActivity((prev) =>
        [event, ...prev.filter((e) => e.id !== event.id)].slice(0, ACTIVITY_CAP),
      );
    }
  }, []);

  const { status, retry } = useEventStream<MetricsFrame>("/metrics/stream", {
    query: { window },
    schema: MetricsFrameSchema,
    onEvent,
    onStreamError: () => setFailed(true),
  });

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);

  const stale = failed || status === "disconnected";
  const age = lastEventAt === null || now === 0 ? null : secondsAgo(lastEventAt, now);
  const data = summary.data;

  return (
    <div className="flex flex-col gap-4" data-stale={stale ? "true" : undefined}>
      {stale ? <StaleBanner asOf={summary.as_of} onRetry={retry} /> : null}
      <KpiRow summary={data} window={window} stale={stale} />
      {children}
      <ActivityFeed events={activity} status={status} ageSeconds={age} />
      <ModelEfficiencyTable
        rows={models}
        window={window}
        autofixRate={data.autofix_rate}
        humanCorrectionRate={data.human_correction_rate}
        cohereUtilisationPct={cohereUtilisationPct}
      />
    </div>
  );
}
