"use client";

import { StatusBadge } from "@/components/common/status-badge";
import { createDataTableColumns, DataTable } from "@/components/common/data-table";
import { GlassPanel, PanelHeader } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import { StateCard } from "@/components/common/state-card";
import type { Schemas } from "@/lib/api/types";
import { formatWorkItemId } from "@/lib/format";

import { formatAge } from "./format";

type Row = Schemas["ReviewQueueRowOut"];

const column = createDataTableColumns<Row>();

const COLUMNS = [
  column.accessor("item_id", {
    header: "Item",
    cell: (info) => (
      <span className="font-mono text-brand-ink">{formatWorkItemId(info.getValue())}</span>
    ),
  }),
  column.accessor("filename", {
    header: "File",
    cell: (info) => <span className="text-[13px]">{info.getValue() ?? "—"}</span>,
  }),
  column.accessor("stage", {
    header: "Stage",
    cell: (info) => (
      <span className="font-mono text-xs text-muted-foreground">{info.getValue().toLowerCase()}</span>
    ),
  }),
  column.accessor("status", {
    header: "Status",
    cell: (info) => <StatusBadge kind="item_state" value={info.getValue()} />,
  }),
  column.accessor("age_seconds", {
    header: "Age",
    cell: (info) => (
      <span className="font-mono text-muted-foreground">{formatAge(info.getValue())}</span>
    ),
  }),
];

/** The Review queue: uploaded items, newest first, with the selected row tinted. */
export function QueueTable({
  rows,
  selectedId,
  onSelect,
}: {
  rows: readonly Row[];
  selectedId: number | null;
  onSelect: (itemId: number) => void;
}): React.JSX.Element {
  return (
    <GlassPanel aria-label="Review queue">
      <PanelHeader title="Review queue">
        <MonoLabel>same stations · high effort</MonoLabel>
      </PanelHeader>
      <DataTable
        columns={COLUMNS}
        data={[...rows]}
        getRowId={(row) => String(row.item_id)}
        selectedRowId={selectedId === null ? null : String(selectedId)}
        onRowClick={(row) => onSelect(row.item_id)}
        enableColumnVisibility={false}
        caption="Items uploaded for in-depth review"
        emptyState={
          <StateCard
            kind="empty"
            label="Empty · queue"
            headline="Nothing under review"
            body="Drop images above. Each one becomes a work item that runs the same stations at high effort."
          />
        }
      />
    </GlassPanel>
  );
}
