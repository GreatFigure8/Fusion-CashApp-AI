"use client";

import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { Schemas } from "@/lib/api/types";

type Point = Schemas["ThroughputPoint"];

const CONFIG = {
  applied: { label: "Applied", color: "var(--chart-1)" },
  escalated: { label: "Escalated", color: "var(--chart-3)" },
} satisfies ChartConfig;

function tick(at: string, hourly: boolean): string {
  const iso = new Date(at).toISOString();
  return hourly ? iso.slice(11, 16) : iso.slice(5, 10);
}

export function ThroughputChart({
  points,
  window,
}: {
  points: readonly Point[];
  window: string;
}) {
  const hourly = window === "24h";
  const unit = hourly ? "h" : "d";
  const peak = points.reduce((max, p) => Math.max(max, p.applied), 0);
  const data = points.map((p) => ({ ...p, label: tick(p.at, hourly) }));
  return (
    <GlassPanel as="section" aria-label="Throughput">
      <PanelHeader title="Throughput">
        <MonoLabel>
          items done per {hourly ? "hour" : "day"} · {window}
        </MonoLabel>
      </PanelHeader>
      <PanelBody>
        <div className="mb-2 flex items-center gap-4 font-mono text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="h-0.5 w-4 bg-[var(--chart-1)]" />
            Applied
          </span>
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="h-0 w-4 border-t-2 border-dashed border-[var(--chart-3)]" />
            Escalated
          </span>
          <span className="ml-auto">
            peak {peak}/{unit}
          </span>
        </div>
        <ChartContainer config={CONFIG} className="h-48 w-full">
          <AreaChart data={data} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="#ffffff14" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={24} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={28} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Area
              type="monotone"
              dataKey="applied"
              stroke="var(--color-applied)"
              fill="var(--color-applied)"
              fillOpacity={0.13}
              strokeWidth={2}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="escalated"
              stroke="var(--color-escalated)"
              fill="none"
              strokeDasharray="4 3"
              strokeWidth={2}
              isAnimationActive={false}
            />
          </AreaChart>
        </ChartContainer>
      </PanelBody>
    </GlassPanel>
  );
}
