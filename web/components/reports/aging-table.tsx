"use client";

import type * as React from "react";

import { DataTable } from "@/components/common/data-table";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";

export type AgingRow = Readonly<{ key: string; label: string; count: number }>;

export function AgingTable({ rows }: { rows: readonly AgingRow[] }): React.JSX.Element {
  return (
    <GlassPanel>
      <PanelHeader title="Aging items" />
      <PanelBody flush>
        <DataTable<AgingRow>
          data={[...rows]}
          getRowId={(r) => r.key}
          caption="Open items by age"
          columns={[
            { id: "age", header: "Age", accessorFn: (r) => r.label },
            {
              id: "items",
              header: "Items",
              accessorFn: (r) => r.count,
              meta: { align: "right", mono: true },
            },
          ]}
        />
      </PanelBody>
    </GlassPanel>
  );
}
