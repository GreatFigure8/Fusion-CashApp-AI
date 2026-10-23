"use client";

import { createDataTableColumns, DataTable } from "@/components/common/data-table";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { Meter } from "@/components/common/meter";
import { MonoLabel } from "@/components/common/mono-label";
import type { Schemas } from "@/lib/api/types";
import { formatPct } from "@/lib/metrics/format";

type Outcome = Schemas["AutofixOutcome"];

const FIXED_TONE_THRESHOLD = 0.6;

export function autofixTone(rate: number | null): "ok" | "warn" {
  return rate !== null && rate > FIXED_TONE_THRESHOLD ? "ok" : "warn";
}

const columnHelper = createDataTableColumns<Outcome>();

const columns = columnHelper.columns([
  columnHelper.accessor("error_code", {
    header: "Error code",
    cell: (info) => <span className="font-mono text-xs">{info.getValue()}</span>,
  }),
  columnHelper.accessor("count", {
    header: "Items",
    cell: (info) => <span className="font-mono tabular-nums">{info.getValue()}</span>,
  }),
  columnHelper.display({
    id: "fixed",
    header: "Fixed",
    cell: ({ row }) => {
      const { rate, error_code: code } = row.original;
      return (
        <span className="flex items-center gap-2">
          <Meter
            value={rate ?? 0}
            tone={autofixTone(rate)}
            size={6}
            label={`${code} fixed rate`}
            className="w-24"
          />
          <span className="font-mono text-xs">{rate === null ? "—" : `${formatPct(rate, 0)} fixed`}</span>
        </span>
      );
    },
  }),
]);

export function AutofixTable({
  outcomes,
  window,
}: {
  outcomes: readonly Outcome[];
  window: string;
}) {
  return (
    <GlassPanel as="section" aria-label="Auto-fix outcomes">
      <PanelHeader title="Auto-fix outcomes">
        <MonoLabel>{window} · by error code</MonoLabel>
      </PanelHeader>
      <PanelBody flush>
        <DataTable
          columns={columns}
          data={[...outcomes]}
          getRowId={(row) => row.error_code}
          caption="Auto-fix outcomes by error code"
          emptyState={
            <p className="text-sm text-muted-foreground">No auto-fix attempts in this window.</p>
          }
        />
      </PanelBody>
    </GlassPanel>
  );
}
