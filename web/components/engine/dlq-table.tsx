"use client";

import Link from "next/link";
import type { Route } from "next";
import { useMemo } from "react";

import { ActionButton } from "@/components/common/action-button";
import { DataTable, type DataTableColumn } from "@/components/common/data-table";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { Pill } from "@/components/common/pill";
import { StateCard } from "@/components/common/state-card";
import type { Schemas } from "@/lib/api/types";
import { formatDateTime, formatWorkItemId } from "@/lib/format";

type Row = Schemas["DeadLetterOut"];

export function DlqTable({
  rows,
  total,
  selected,
  onSelectedChange,
  enabled,
  canControl,
  onReplay,
}: Readonly<{
  rows: readonly Row[];
  total: number;
  selected: ReadonlySet<string>;
  onSelectedChange: (next: Set<string>) => void;
  enabled: boolean;
  canControl: boolean;
  onReplay: () => void;
}>) {
  const columns = useMemo<DataTableColumn<Row>[]>(
    () => [
      {
        id: "select",
        header: "Select",
        cell: ({ row }) => (
          <input
            type="checkbox"
            aria-label={`Select ${row.original.event_id}`}
            checked={selected.has(row.original.event_id)}
            disabled={!enabled}
            onChange={(e) => {
              const next = new Set(selected);
              if (e.target.checked) next.add(row.original.event_id);
              else next.delete(row.original.event_id);
              onSelectedChange(next);
            }}
          />
        ),
      },
      {
        id: "event",
        header: "Event",
        cell: ({ row }) => <span className="font-mono">{row.original.event_id}</span>,
      },
      {
        id: "stage",
        header: "Stage",
        cell: ({ row }) => <span className="font-mono">{row.original.stage}</span>,
      },
      {
        id: "item",
        header: "Item",
        cell: ({ row }) =>
          row.original.item_id === null ? (
            "—"
          ) : (
            <Link
              href={`/items/${row.original.item_id}` as Route}
              className="font-mono underline-offset-2 hover:underline"
            >
              {formatWorkItemId(row.original.item_id)}
            </Link>
          ),
      },
      {
        id: "error",
        header: "Error",
        cell: ({ row }) => (
          <Pill tone="err" mono>
            {row.original.error_code ?? "UNKNOWN"}
          </Pill>
        ),
      },
      {
        id: "attempts",
        header: "Attempts",
        meta: { align: "right", mono: true },
        cell: ({ row }) => <span className="font-mono">{row.original.attempts}</span>,
      },
      {
        id: "dead_since",
        header: "Dead since",
        cell: ({ row }) => formatDateTime(row.original.dead_since),
      },
    ],
    [selected, enabled, onSelectedChange],
  );

  return (
    <GlassPanel as="section" aria-label="Dead-letter queue">
      <PanelHeader title="Dead-letter queue">
        <Pill tone={total > 0 ? "err" : "muted"}>{total} events</Pill>
        <ActionButton
          variant="default"
          size="sm"
          disabled={!enabled || selected.size === 0}
          onClick={onReplay}
        >
          {canControl ? `Replay ${selected.size} selected…` : "Replay · needs admin"}
        </ActionButton>
      </PanelHeader>
      <PanelBody flush>
        {rows.length === 0 ? (
          <div className="p-4">
            <StateCard
              kind="empty"
              label="Empty · DLQ"
              headline="No dead letters"
              body="Every event is inside its retry budget."
            />
          </div>
        ) : (
          <DataTable<Row>
            columns={columns}
            data={[...rows]}
            getRowId={(r) => r.event_id}
            caption="Dead-letter events"
          />
        )}
      </PanelBody>
    </GlassPanel>
  );
}
