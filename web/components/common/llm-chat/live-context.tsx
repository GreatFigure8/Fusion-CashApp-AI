"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import { Pill } from "@/components/common/pill";
import { useEventStream } from "@/hooks/use-event-stream";
import { z } from "zod";

import { loadLiveContext, type LiveContextSnapshot } from "./chat-server-actions";
import { TOOL_GROUPS, type ChatToolsOut, type ToolGroup } from "./chat-schemas";
import { COPY, TOOL_GROUP_ABILITIES } from "./defaults";

const REFRESH_MIN_MS = 1500;
const anyPayload = z.unknown();

/** Each source keeps its last good value; a failing source marks only itself stale. */
type Source<T> = { value: T | null; stale: boolean };

type Live = {
  summary: Source<{ automationRate: number | null; openExceptions: number | null }>;
  engine: Source<{ busLag: number | null; applyState: string | null }>;
  mcp: Source<"healthy" | "unhealthy" | "unknown">;
};

const EMPTY: Live = {
  summary: { value: null, stale: false },
  engine: { value: null, stale: false },
  mcp: { value: null, stale: false },
};

function merge<T>(prev: Source<T>, next: { ok: true; value: T } | { ok: false }): Source<T> {
  return next.ok ? { value: next.value, stale: false } : { value: prev.value, stale: true };
}

function Row({ label, children, stale }: { label: string; children: ReactNode; stale?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 text-[13px]">
      <dt className="text-soft">{label}</dt>
      <dd className="font-mono">
        {children}
        {stale ? (
          <span className="ml-1 text-warn" title="Could not refresh; showing the last value">
            (stale)
          </span>
        ) : null}
      </dd>
    </div>
  );
}

const DASH = "—";

type LiveContextProps = { tools: ChatToolsOut | null; className?: string };

export function LiveContext({ tools, className }: LiveContextProps) {
  const [live, setLive] = useState<Live>(EMPTY);
  const lastRun = useRef(0);

  const refresh = useCallback(async () => {
    const now = Date.now();
    if (now - lastRun.current < REFRESH_MIN_MS) return;
    lastRun.current = now;
    let snap: LiveContextSnapshot | null = null;
    try {
      snap = await loadLiveContext();
    } catch {
      snap = null;
    }
    setLive((prev) =>
      snap === null
        ? {
            summary: { ...prev.summary, stale: true },
            engine: { ...prev.engine, stale: true },
            mcp: { ...prev.mcp, stale: true },
          }
        : {
            summary: merge(prev.summary, snap.summary),
            engine: merge(prev.engine, snap.engine),
            // A 403 or failure reads "unknown", not an error.
            mcp: snap.mcp.ok
              ? { value: snap.mcp.value, stale: false }
              : { value: "unknown", stale: false },
          },
    );
  }, []);

  useEffect(() => {
    // Initial read; later reads come from the two streams below.
    const timer = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(timer);
  }, [refresh]);

  useEventStream<unknown>("/metrics/stream", {
    schema: anyPayload,
    onEvent: (e) => {
      if (e.event === "summary") void refresh();
    },
  });
  useEventStream<unknown>("/engine/stream", {
    schema: anyPayload,
    onEvent: (e) => {
      if (e.event === "status") void refresh();
    },
  });

  const { summary, engine, mcp } = live;
  const rate = summary.value?.automationRate;
  const open = summary.value?.openExceptions;
  const catalog = tools ?? [];

  return (
    <GlassPanel as="aside" aria-label="Live context" className={className}>
      <PanelHeader title="Live context" titleSize="label" />
      <PanelBody>
        <dl className="divide-y divide-line">
          <Row label="Automation · 7d" stale={summary.stale}>
            {rate === null || rate === undefined ? DASH : `${(rate * 100).toFixed(1)}%`}
          </Row>
          <Row label="Open exceptions" stale={summary.stale}>
            {open === null || open === undefined ? DASH : open.toLocaleString("en-US")}
          </Row>
          <Row label="Bus lag" stale={engine.stale}>
            {engine.value?.busLag == null ? DASH : engine.value.busLag.toLocaleString("en-US")}
          </Row>
          <Row label="Apply" stale={engine.stale}>
            {engine.value?.applyState ?? DASH}
          </Row>
          <Row label="Fusion reads">{mcp.value ?? "unknown"}</Row>
        </dl>
        <MonoLabel as="h3" className="mt-4 mb-1 text-soft">
          Your tools
        </MonoLabel>
        <ul className="divide-y divide-line">
          {TOOL_GROUPS.map((group: ToolGroup) => {
            const entry = catalog.find((g) => g.group === group);
            if (!entry) return null;
            return (
              <li key={group} className="flex items-center justify-between py-1.5 text-[13px]">
                <span>{TOOL_GROUP_ABILITIES[group]}</span>
                <Pill tone={entry.allowed ? "ok" : "muted"} mono>
                  {entry.allowed ? "Allowed" : "Denied"}
                </Pill>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-[12px] text-soft">{COPY.footnote}</p>
      </PanelBody>
    </GlassPanel>
  );
}
