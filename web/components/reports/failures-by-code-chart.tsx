"use client";

import type * as React from "react";
import { Bar, BarChart, XAxis, YAxis } from "recharts";

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
    <section className="flex flex-col gap-2">
      <h2 className="text-base font-medium">Failures by error code</h2>
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
            <YAxis type="category" dataKey="code" width={190} tickLine={false} axisLine={false} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Bar dataKey="count" fill="var(--color-count)" radius={4} />
          </BarChart>
        </ChartContainer>
      )}
    </section>
  );
}
