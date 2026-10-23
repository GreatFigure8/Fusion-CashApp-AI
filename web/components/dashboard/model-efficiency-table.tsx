"use client";

import { createDataTableColumns, DataTable } from "@/components/common/data-table";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import { Money } from "@/components/common/money";
import { Pill } from "@/components/common/pill";
import type { Schemas } from "@/lib/api/types";
import { humanizeEnum } from "@/lib/format";
import { formatAccuracy, formatPct } from "@/lib/metrics/format";

type Row = Schemas["ModelEfficiencyRow"];

const columnHelper = createDataTableColumns<Row>();

const columns = columnHelper.columns([
  columnHelper.accessor("role", {
    header: "Role",
    cell: (info) => humanizeEnum(info.getValue()),
  }),
  columnHelper.accessor("model_id", {
    header: "Model",
    cell: (info) => <span className="font-mono text-xs text-[var(--acc-hi)]">{info.getValue()}</span>,
  }),
  columnHelper.accessor("calls", {
    header: "Calls",
    cell: (info) => <span className="font-mono tabular-nums">{info.getValue()}</span>,
  }),
  columnHelper.display({
    id: "cost",
    header: "Cost",
    cell: ({ row }) =>
      row.original.cost_basis === "CLUSTER" ? (
        <span className="font-mono text-xs text-muted-foreground">cluster</span>
      ) : (
        <Money amount={row.original.cost_usd} currency="USD" />
      ),
  }),
  columnHelper.display({
    id: "cost_unknown",
    header: "Cost unknown",
    cell: ({ row }) =>
      row.original.cost_basis === "CLUSTER" ? (
        <span className="font-mono text-xs text-muted-foreground">n/a</span>
      ) : (
        <span className="font-mono text-xs">{formatPct(row.original.cost_unknown_share, 0)}</span>
      ),
  }),
  columnHelper.display({
    id: "agreement",
    header: "Agreement",
    cell: ({ row }) => (
      <span className="font-mono text-xs">{formatPct(row.original.agreement_rate)}</span>
    ),
  }),
  columnHelper.display({
    id: "human_correction",
    header: "Human corr.",
    cell: ({ row }) => (
      <span className="font-mono text-xs">{formatPct(row.original.human_correction_rate)}</span>
    ),
  }),
  columnHelper.display({
    id: "accuracy",
    header: "Accuracy",
    cell: ({ row }) => (
      <span className="font-mono text-xs">
        {formatAccuracy(row.original.accuracy, row.original.accuracy_n)}
      </span>
    ),
  }),
]);

export function ModelEfficiencyTable({
  rows,
  window,
  autofixRate,
  humanCorrectionRate,
  cohereUtilisationPct,
}: {
  rows: readonly Row[];
  window: string;
  autofixRate: number | null;
  humanCorrectionRate: number | null;
  /** 0..100, or null when the cluster is not measured. */
  cohereUtilisationPct: number | null;
}) {
  return (
    <GlassPanel as="section" aria-label="Model efficiency">
      <PanelHeader title="Model efficiency">
        <MonoLabel>{window} · accuracy only where people corrected</MonoLabel>
      </PanelHeader>
      <PanelBody flush>
        <DataTable
          columns={columns}
          data={[...rows]}
          getRowId={(row) => `${row.role}:${row.model_id}`}
          caption="Model efficiency"
          emptyState={
            <p className="text-sm text-muted-foreground">No model calls in this window.</p>
          }
        />
        <div className="flex flex-wrap gap-2 border-t border-white/10 p-3">
          <Pill tone="ok" mono>
            Auto-fix rate {formatPct(autofixRate)}
          </Pill>
          <Pill tone="warn" mono>
            Human-correction rate {formatPct(humanCorrectionRate)}
          </Pill>
          <Pill tone="accent" mono>
            Cohere cluster utilisation{" "}
            {cohereUtilisationPct === null ? "—" : `${cohereUtilisationPct.toFixed(0)}%`}
          </Pill>
        </div>
      </PanelBody>
    </GlassPanel>
  );
}
