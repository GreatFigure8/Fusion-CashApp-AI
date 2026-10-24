"use client";

import { createDataTableColumns, DataTable } from "@/components/common/data-table";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import { Money } from "@/components/common/money";
import type { Schemas } from "@/lib/api/types";

type Row = Schemas["LabMoneyByCurrencyOut"];

const col = createDataTableColumns<Row>();

const columns = col.columns([
  col.accessor("currency", {
    header: "Currency",
    cell: (info) => <span className="font-mono">{info.getValue()}</span>,
  }),
  col.accessor("newly_matched", {
    header: "Newly matched",
    meta: { align: "right", mono: true },
    cell: (info) => <Money amount={info.getValue()} currency={info.row.original.currency} />,
  }),
  col.accessor("newly_unmatched", {
    header: "Newly unmatched",
    meta: { align: "right", mono: true },
    cell: (info) => <Money amount={info.getValue()} currency={info.row.original.currency} />,
  }),
  col.accessor("items", {
    header: "Items",
    meta: { align: "right", mono: true },
    cell: (info) => <span className="font-mono tabular-nums">{info.getValue()}</span>,
  }),
]);

/** One row per currency, straight from the API. Never summed across currencies. */
export function MoneyAffectedTable({ rows }: { rows: readonly Row[] }) {
  return (
    <GlassPanel aria-label="Money affected">
      <PanelHeader title="Money affected">
        <MonoLabel>by currency</MonoLabel>
      </PanelHeader>
      <PanelBody flush className="overflow-x-auto">
        <DataTable
          columns={columns}
          data={[...rows]}
          getRowId={(row) => row.currency}
          enableColumnVisibility={false}
          caption="Money affected by currency"
          emptyState="No money moves."
        />
      </PanelBody>
    </GlassPanel>
  );
}
