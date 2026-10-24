"use client";

import type { DataTableColumn } from "@/components/common/data-table";
import { Lock, MoreHorizontal } from "lucide-react";
import { useTransition } from "react";
import { toast } from "sonner";

import { dequeueAction } from "@/app/(shell)/exceptions/_lib/actions";
import { Money } from "@/components/common/money";
import { Pill } from "@/components/common/pill";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Schemas } from "@/lib/api/types";
import { formatDuration, formatWorkItemId } from "@/lib/format";

import { lockOwnerLabel } from "./list-format";
import { lockErrorToast } from "./lock-messages";
import { REASON_TONE, reasonLabel } from "./reason";

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
  meSubject: string | null;
}): DataTableColumn<ExceptionRow>[] {
  return [
    {
      id: "id",
      header: "Item",
      cell: ({ row }) => (
        <span className="font-mono text-brand-ink">{formatWorkItemId(row.original.id)}</span>
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
      meta: { align: "right", mono: true },
      cell: ({ row }) => (
        <Money amount={row.original.amount} currency={row.original.currency} />
      ),
    },
    {
      id: "error_code",
      header: "Reason",
      cell: ({ row }) =>
        row.original.error_code ? (
          <Pill tone={REASON_TONE[row.original.error_code]}>
            {reasonLabel(row.original.error_code)}
          </Pill>
        ) : (
          "—"
        ),
    },
    {
      id: "age",
      header: "Age",
      meta: { align: "right", mono: true },
      cell: ({ row }) => (
        <span className="text-muted-foreground">{formatDuration(row.original.age_s)}</span>
      ),
    },
    {
      id: "lock",
      header: "Lock",
      cell: ({ row }) => {
        const label = lockOwnerLabel(row.original.lock, options.meSubject);
        return label ? (
          <span className="inline-flex items-center gap-1 text-xs text-locked-ink">
            <Lock aria-hidden className="size-3.5" />
            {label}
          </span>
        ) : null;
      },
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
