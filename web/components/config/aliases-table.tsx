"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";

import { DataTable, type DataTableProps } from "@/components/common/data-table";
import { EmptyState } from "@/components/common/empty-state";
import { Button } from "@/components/ui/button";
import type { Schemas } from "@/lib/api/types";
import { formatRelative, formatWorkItemId } from "@/lib/format";

import { RetireAliasDialog } from "./retire-alias-dialog";

type Alias = Schemas["AliasOut"];

const KIND_LABEL: Record<Alias["kind"], string> = {
  name: "Name",
  bank_account: "Bank account",
  reference: "Reference",
};

/** The active payer aliases, paged by the URL (`apage`). Retire is offered only to writers. */
export function AliasesTable({
  items,
  total,
  page,
  pageSize,
  canEdit,
}: {
  items: Alias[];
  total: number;
  page: number;
  pageSize: number;
  canEdit: boolean;
}) {
  const pathname = usePathname();
  const params = useSearchParams();
  const [retiring, setRetiring] = useState<Alias | null>(null);

  const columns: DataTableProps<Alias>["columns"] = [
    {
      id: "alias_text",
      header: "Alias",
      cell: ({ row }) => <span className="font-mono">{row.original.alias_text}</span>,
    },
    { id: "kind", header: "Kind", cell: ({ row }) => KIND_LABEL[row.original.kind] },
    {
      id: "customer_number",
      header: "Maps to customer",
      cell: ({ row }) => <span className="font-mono">{row.original.customer_number}</span>,
    },
    {
      id: "learned_from",
      header: "Learned from",
      cell: ({ row }) =>
        row.original.learned_from_item_id === null ? (
          "—"
        ) : (
          <Link
            href={`/items/${row.original.learned_from_item_id}` as Route}
            className="font-mono underline-offset-2 hover:underline"
          >
            {formatWorkItemId(row.original.learned_from_item_id)}
          </Link>
        ),
    },
    { id: "uses", header: "Uses", cell: ({ row }) => row.original.uses },
    {
      id: "last_used_at",
      header: "Last used",
      cell: ({ row }) =>
        row.original.last_used_at ? formatRelative(row.original.last_used_at) : "Never",
    },
    ...(canEdit
      ? ([
          {
            id: "retire",
            header: "Retire",
            cell: ({ row }) => (
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label={`Retire alias ${row.original.alias_text}`}
                onClick={() => setRetiring(row.original)}
              >
                Retire
              </Button>
            ),
          },
        ] satisfies DataTableProps<Alias>["columns"])
      : []),
  ];

  function hrefForPage(p: number): string {
    const next = new URLSearchParams(params.toString());
    next.set("apage", String(p));
    return `${pathname}?${next.toString()}`;
  }

  return (
    <>
      <DataTable
        columns={columns}
        data={items}
        getRowId={(a) => String(a.id)}
        caption="Active payer aliases"
        enableColumnVisibility={false}
        pagination={{ page, pageSize, total, hrefForPage }}
        emptyState={<EmptyState title="No active payer aliases." />}
      />
      <RetireAliasDialog alias={retiring} onClose={() => setRetiring(null)} />
    </>
  );
}
