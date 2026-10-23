"use client";

import type * as React from "react";

import { DataTable } from "@/components/common/data-table";
import { Money } from "@/components/common/money";
import type { Schemas } from "@/lib/api/types";

type Row = Schemas["PartiallyPaidRowOut"];

export function PartiallyPaidTable({
  rows,
  emptyState,
}: {
  rows: readonly Row[];
  emptyState: React.ReactNode;
}): React.JSX.Element {
  return (
    <DataTable<Row>
      data={[...rows]}
      getRowId={(r) => `${r.item_id}:${r.invoice_number}`}
      emptyState={emptyState}
      caption="Partially paid invoices"
      columns={[
        {
          id: "invoice_number",
          header: "Invoice #",
          accessorFn: (r) => r.invoice_number,
          cell: ({ row }) => <span className="font-mono tabular-nums">{row.original.invoice_number}</span>,
        },
        {
          id: "customer",
          header: "Customer",
          accessorFn: (r) => r.customer_account_number ?? "",
          cell: ({ row }) =>
            [row.original.customer_account_number, row.original.customer_name]
              .filter((v) => v)
              .join(" · ") || "—",
        },
        {
          id: "original",
          header: "Original",
          accessorFn: (r) => r.original,
          meta: { align: "right" },
          cell: ({ row }) => (
            <Money
              className="block text-right"
              amount={row.original.original}
              currency={row.original.currency}
            />
          ),
        },
        {
          id: "paid",
          header: "Paid",
          accessorFn: (r) => r.paid,
          meta: { align: "right" },
          cell: ({ row }) => (
            <Money
              className="block text-right"
              amount={row.original.paid}
              currency={row.original.currency}
            />
          ),
        },
        {
          id: "remaining",
          header: "Remaining",
          accessorFn: (r) => r.remaining,
          meta: { align: "right" },
          cell: ({ row }) => (
            <Money
              className="block text-right"
              amount={row.original.remaining}
              currency={row.original.currency}
            />
          ),
        },
        {
          id: "short_pay_reason",
          header: "Short-pay reason",
          accessorFn: (r) => r.short_pay_reason,
        },
        {
          id: "work_item",
          header: "WI",
          accessorFn: (r) => r.item_id,
          // Partially paid items are DONE, so they open in the item view, not the workbench.
          cell: ({ row }) => (
            <a className="font-mono text-brand-ink underline-offset-2 hover:underline" href={`/items/${row.original.item_id}`}>
              WI-{row.original.item_id}
            </a>
          ),
        },
      ]}
    />
  );
}
