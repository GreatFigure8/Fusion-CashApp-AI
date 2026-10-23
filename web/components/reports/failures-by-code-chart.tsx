"use client";

import type * as React from "react";
import { Bar, BarChart, XAxis, YAxis } from "recharts";

import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

export type FailureRow = Readonly<{ error_code: string; count: number }>;

const config = {
  count: { label: "Items", color: "var(--status-error)" },
} satisfies ChartConfig;

export function FailuresByCodeChart({
  rows,
}: {
  rows: readonly FailureRow[];
}): React.JSX.Element {
  const data = rows.map((r) => ({ code: r.error_code, count: r.count }));
  return (
    <GlassPanel>
      <PanelHeader title="Failures by error code" />
      <PanelBody>
        {data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No failures on this day.</p>
        ) : (
          <ChartContainer
            config={config}
            className="w-full"
            style={{ height: Math.max(120, data.length * 36 + 24) }}
          >
            <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
              <XAxis type="number" hide allowDecimals={false} />
              <YAxis
                type="category"
                dataKey="code"
                width={190}
                tickLine={false}
                axisLine={false}
                className="font-mono"
              />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar dataKey="count" fill="var(--color-count)" radius={4} />
            </BarChart>
          </ChartContainer>
        )}
      </PanelBody>
    </GlassPanel>
  );
}
