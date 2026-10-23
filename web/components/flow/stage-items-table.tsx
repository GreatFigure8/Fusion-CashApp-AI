"use client";

import { LockIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { createDataTableColumns, DataTable } from "@/components/common/data-table";
import { Money } from "@/components/common/money";
import { StateCard } from "@/components/common/state-card";
import { StatusBadge } from "@/components/common/status-badge";
import { useFlowStream } from "@/components/shell/flow-stream";
import type { Schemas } from "@/lib/api/types";
import { formatDateTime, formatRelative, formatWorkItemId, humanizeEnum } from "@/lib/format";

type StageItem = Schemas["StageItemOut"];
type ItemChanged = Schemas["ItemChangedOut"];
type Tile = Schemas["FlowTile"];

const columnHelper = createDataTableColumns<StageItem>();

/** Has the item left this tile? An awaiting tile is a state; every other tile is a stage. */
function hasMoved(tile: Tile, item: StageItem): boolean {
  return tile === "AWAITING_RECEIPT" ? item.state !== "AWAITING_RECEIPT" : item.stage !== tile;
}

const columns = (tile: Tile) =>
  columnHelper.columns([
    columnHelper.accessor("id", {
      header: "WI",
      cell: (info) => <span className="font-mono">{formatWorkItemId(info.getValue())}</span>,
    }),
    columnHelper.accessor((row) => row.payer_name ?? "", {
      id: "payer",
      header: "Payer",
      cell: (info) => info.getValue() || <span className="text-muted-foreground">—</span>,
    }),
    columnHelper.display({
      id: "amount",
      header: "Amount",
      cell: ({ row }) => (
        <div className="text-right">
          <Money amount={row.original.amount} currency={row.original.currency} />
        </div>
      ),
    }),
    columnHelper.accessor("received_at", {
      header: "Received",
      cell: (info) => (
        <time dateTime={info.getValue()} title={formatDateTime(info.getValue())}>
          {formatRelative(info.getValue())}
        </time>
      ),
    }),
    columnHelper.accessor("attempts", {
      header: "Attempts",
      cell: (info) => <span className="tabular-nums">{info.getValue()}</span>,
    }),
    columnHelper.display({
      id: "status",
      header: "Status",
      cell: ({ row }) => {
        const item = row.original;
        if (hasMoved(tile, item)) {
          return (
            <span className="text-muted-foreground" data-slot="moved">
              Moved to {humanizeEnum(item.state === "AWAITING_RECEIPT" ? "AWAITING_RECEIPT" : item.stage)}
            </span>
          );
        }
        return (
          <span className="flex flex-wrap items-center gap-1">
            <StatusBadge kind="item_state" value={item.state} />
            {item.payment_status ? (
              <StatusBadge kind="payment_status" value={item.payment_status} />
            ) : null}
          </span>
        );
      },
    }),
    columnHelper.display({
      id: "lock",
      header: "Lock",
      cell: ({ row }) =>
        row.original.lock ? (
          <span className="flex items-center gap-1 text-locked-ink" data-slot="lock-owner">
            <LockIcon aria-hidden className="size-3.5" />
            {row.original.lock.owner_name}
          </span>
        ) : null,
    }),
  ]);

/** The items behind a tile. `item_changed` events patch rows in place, with no reload. */
export function StageItemsTable({
  tile,
  data,
  stateFilter,
}: {
  tile: Tile;
  data: Schemas["StageItemsOut"];
  stateFilter: Schemas["ItemState"] | null;
}) {
  const { subscribeItemChanged } = useFlowStream();
  const [patches, setPatches] = useState<Record<number, ItemChanged>>({});

  useEffect(
    () =>
      subscribeItemChanged((event) => {
        setPatches((previous) => ({ ...previous, [event.id]: event }));
      }),
    [subscribeItemChanged],
  );

  const rows = useMemo<StageItem[]>(
    () =>
      data.items.map((item) => {
        const patch = patches[item.id];
        return patch
          ? {
              ...item,
              stage: patch.stage,
              state: patch.state,
              lock: patch.lock,
              payment_status: patch.payment_status,
            }
          : item;
      }),
    [data.items, patches],
  );
  const tableColumns = useMemo(() => columns(tile), [tile]);

  const hrefForPage = (page: number) => {
    const query = new URLSearchParams({ page: String(page) });
    if (stateFilter) query.set("state", stateFilter);
    return `/flow/${tile.toLowerCase()}?${query.toString()}`;
  };

  return (
    <DataTable
      columns={tableColumns}
      data={rows}
      getRowId={(row) => String(row.id)}
      rowHref={(row) => `/items/${row.id}?from=${tile}`}
      pagination={{ page: data.page, pageSize: data.page_size, total: data.total, hrefForPage }}
      densityStorageKey="cashapp.table-density"
      caption={`${humanizeEnum(tile)} items`}
      emptyState={<StateCard kind="empty" headline="Nothing here." body="No items are at this stage." />}
    />
  );
}
