"use client";

import type { DataTableColumn } from "@/components/common/data-table";
import { Lock, MoreHorizontal } from "lucide-react";
import { useTransition } from "react";
import { toast } from "sonner";

import { dequeueAction } from "@/app/(shell)/exceptions/_lib/actions";
import { Money } from "@/components/common/money";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Schemas } from "@/lib/api/types";
import { formatDuration, formatWorkItemId } from "@/lib/format";

import { lockErrorToast } from "./lock-messages";

export type ExceptionRow = Schemas["ExceptionRowOut"];

function RowMenu({
  row,
  canWork,
  onOpen,
}: Readonly<{
  row: ExceptionRow;
  canWork: boolean;
  onOpen: (id: number) => void;
}>) {
  const [pending, startTransition] = useTransition();

  const dequeue = () =>
    startTransition(async () => {
      const result = await dequeueAction({ itemId: row.id });
      if (!result.ok) {
        toast.error(lockErrorToast(result.error) ?? result.error.message);
        return;
      }
      onOpen(row.id);
    });

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Actions for ${formatWorkItemId(row.id)}`}
            disabled={pending}
            onClick={(e) => e.stopPropagation()}
          />
        }
      >
        <MoreHorizontal />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => onOpen(row.id)}>Open</DropdownMenuItem>
        {canWork && !row.lock ? (
          <DropdownMenuItem onClick={dequeue}>Dequeue</DropdownMenuItem>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function buildExceptionColumns(options: {
  canWork: boolean;
  onOpen: (id: number) => void;
}): DataTableColumn<ExceptionRow>[] {
  return [
    {
      id: "id",
      header: "WI",
      cell: ({ row }) => (
        <span className="font-mono">{formatWorkItemId(row.original.id)}</span>
      ),
    },
    {
      id: "payer",
      header: "Payer",
      cell: ({ row }) => row.original.payer_name ?? "—",
    },
    {
      id: "amount",
      header: "Amount",
      cell: ({ row }) => (
        <Money amount={row.original.amount} currency={row.original.currency} />
      ),
    },
    {
      id: "payment_date",
      header: "Payment date",
      cell: ({ row }) => row.original.payment_date ?? "—",
    },
    {
      id: "error_code",
      header: "Error",
      cell: ({ row }) =>
        row.original.error_code ? (
          <Badge variant="outline" className="font-mono">
            {row.original.error_code}
          </Badge>
        ) : (
          "—"
        ),
    },
    {
      id: "autofix",
      header: "Auto-fixes",
      cell: ({ row }) => (
        <span className="font-mono tabular-nums">
          {row.original.autofix_tried} / {row.original.autofix_limit}
        </span>
      ),
    },
    {
      id: "age",
      header: "Age",
      cell: ({ row }) => formatDuration(row.original.age_s),
    },
    {
      id: "lock",
      header: "Lock",
      cell: ({ row }) =>
        row.original.lock ? (
          <span className="inline-flex items-center gap-1 text-status-locked">
            <Lock aria-hidden className="size-3.5" />
            {row.original.lock.owner_name}
          </span>
        ) : null,
    },
    {
      id: "actions",
      header: () => <span className="sr-only">Actions</span>,
      cell: ({ row }) => (
        <RowMenu
          row={row.original}
          canWork={options.canWork}
          onOpen={options.onOpen}
        />
      ),
    },
  ];
}
