"use client";

import Link from "next/link";
import type { Route } from "next";
import { useState } from "react";

import { createDataTableColumns, DataTable } from "@/components/common/data-table";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { Pill } from "@/components/common/pill";
import { buttonVariants } from "@/components/ui/button";
import type { Schemas } from "@/lib/api/types";
import { formatMoney, formatWorkItemId, humanizeEnum } from "@/lib/format";
import { csvHref, OUTCOME_TONE } from "@/lib/lab/view";

type Row = Schemas["ReplayItemOut"];

const PAGE_SIZE = 25;
const col = createDataTableColumns<Row>();

const outcome = (value: Schemas["ReplayOutcome"]) => (
  <Pill tone={OUTCOME_TONE[value]} dot>
    {humanizeEnum(value)}
  </Pill>
);

const columns = col.columns([
  col.accessor("item_id", {
    header: "Item",
    cell: (info) => (
      <Link
        href={`/items/${info.getValue()}` as Route}
        className="font-mono text-brand-ink underline-offset-2 hover:underline"
      >
        {formatWorkItemId(info.getValue())}
      </Link>
    ),
  }),
  col.display({
    id: "amount",
    header: "Amount",
    meta: { align: "right", mono: true },
    cell: ({ row }) => (
      <span className="font-mono tabular-nums">
        {formatMoney(row.original.amount, row.original.currency)}
      </span>
    ),
  }),
  col.accessor("before", { header: "Before", cell: (info) => outcome(info.getValue()) }),
  col.accessor("after", { header: "After", cell: (info) => outcome(info.getValue()) }),
]);

/** The items whose outcome changes, with the CSV export. Scrolls sideways inside the card. */
export function ChangedItemsTable({ replayId, items }: { replayId: string; items: readonly Row[] }) {
  const [page, setPage] = useState(1);
  const csv = csvHref(replayId);
  const slice = items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  return (
    <GlassPanel aria-label="Items that change">
      <PanelHeader title="Items that change">
        {csv ? (
          <a href={csv} download className={buttonVariants({ variant: "outline", size: "sm" })}>
            Export CSV
          </a>
        ) : null}
      </PanelHeader>
      <PanelBody flush className="overflow-x-auto">
        <DataTable
          columns={columns}
          data={slice}
          getRowId={(row) => String(row.item_id)}
          enableColumnVisibility={false}
          caption="Items that change"
          emptyState="No item changes."
          pagination={{ page, pageSize: PAGE_SIZE, total: items.length, onPageChange: setPage }}
        />
      </PanelBody>
    </GlassPanel>
  );
}
