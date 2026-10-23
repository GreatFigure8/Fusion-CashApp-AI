"use client";

import {
  columnVisibilityFeature,
  createColumnHelper,
  createSortedRowModel,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  sortFn_text,
  tableFeatures,
  useTable,
  type ColumnDef,
  type RowData,
  type SortingState,
} from "@tanstack/react-table";
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  Columns3Icon,
} from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

/** Per-column presentation hints, read from `columnDef.meta`. */
export type DataTableColumnMeta = {
  align?: "left" | "right";
  mono?: boolean;
};

/** The features every data table registers: client sorting and column visibility. */
export const dataTableFeatures = tableFeatures({
  columnMeta: {} as DataTableColumnMeta,
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric, text: sortFn_text, basic: sortFn_basic },
  columnVisibilityFeature,
});

type DataTableFeatures = typeof dataTableFeatures;

// `any` mirrors the column helper's own return type, which keeps each accessor's value type.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type DataTableColumn<T extends RowData> = ColumnDef<DataTableFeatures, T, any>;

/** Build columns with `createDataTableColumns<Row>()`; accessor value types are preserved. */
export function createDataTableColumns<T extends RowData>() {
  return createColumnHelper<DataTableFeatures, T>();
}

export type DataTableDensity = "compact" | "comfortable";

export type DataTableProps<T extends RowData> = {
  columns: DataTableColumn<T>[];
  data: T[];
  getRowId: (row: T) => string;
  rowHref?: (row: T) => string;
  onRowClick?: (row: T) => void;
  pagination?: {
    page: number;
    pageSize: number;
    total: number;
    hrefForPage?: (p: number) => string;
    onPageChange?: (p: number) => void;
  };
  initialSorting?: SortingState;
  enableColumnVisibility?: boolean;
  density?: DataTableDensity;
  densityStorageKey?: string;
  emptyState?: ReactNode;
  loading?: boolean;
  caption?: string;
  /** The row shown as selected (tinted, `aria-selected`). */
  selectedRowId?: string | null;
};

const DENSITY_EVENT = "data-table-density";

function readDensity(key: string | undefined, fallback: DataTableDensity): DataTableDensity {
  if (!key) return fallback;
  try {
    const stored = window.localStorage.getItem(key);
    return stored === "compact" || stored === "comfortable" ? stored : fallback;
  } catch {
    return fallback;
  }
}

function subscribeDensity(callback: () => void): () => void {
  window.addEventListener("storage", callback);
  window.addEventListener(DENSITY_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(DENSITY_EVENT, callback);
  };
}

/** The row density, remembered per table in localStorage (every access guarded). */
function useDensity(
  key: string | undefined,
  fallback: DataTableDensity,
): [DataTableDensity, (next: DataTableDensity) => void] {
  const [memory, setMemory] = useState<DataTableDensity | null>(null);
  const stored = useSyncExternalStore(
    subscribeDensity,
    () => readDensity(key, fallback),
    () => fallback,
  );
  const set = (next: DataTableDensity) => {
    setMemory(next);
    if (!key) return;
    try {
      window.localStorage.setItem(key, next);
    } catch {
      // Storage can be blocked; the choice then lasts for this page view only.
    }
    window.dispatchEvent(new Event(DENSITY_EVENT));
  };
  return [memory ?? stored, set];
}

function PageControls({
  pagination,
}: {
  pagination: NonNullable<DataTableProps<RowData>["pagination"]>;
}) {
  const { page, pageSize, total, hrefForPage, onPageChange } = pagination;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(total, page * pageSize);

  const control = (target: number, label: string, icon: ReactNode, disabled: boolean) => {
    if (hrefForPage && !disabled) {
      return (
        <Button
          variant="outline"
          size="icon-sm"
          aria-label={label}
          render={<Link href={hrefForPage(target) as Route} />}
        >
          {icon}
        </Button>
      );
    }
    return (
      <Button
        variant="outline"
        size="icon-sm"
        aria-label={label}
        disabled={disabled}
        onClick={() => onPageChange?.(target)}
      >
        {icon}
      </Button>
    );
  };

  return (
    <nav
      aria-label="Pagination"
      className="flex items-center justify-between gap-2 border-t px-3 py-2 text-xs text-muted-foreground"
    >
      <span className="tabular-nums">
        {first}–{last} of {total}
      </span>
      <span className="flex items-center gap-2">
        <span className="tabular-nums">
          Page {page} of {pages}
        </span>
        {control(page - 1, "Previous page", <ChevronLeftIcon />, page <= 1)}
        {control(page + 1, "Next page", <ChevronRightIcon />, page >= pages)}
      </span>
    </nav>
  );
}

export function DataTable<T extends RowData>({
  columns,
  data,
  getRowId,
  rowHref,
  onRowClick,
  pagination,
  initialSorting,
  enableColumnVisibility = true,
  density = "compact",
  densityStorageKey,
  emptyState,
  loading = false,
  caption,
  selectedRowId,
}: DataTableProps<T>) {
  const router = useRouter();
  const [activeDensity, setDensity] = useDensity(densityStorageKey, density);

  const table = useTable({
    features: dataTableFeatures,
    columns,
    data,
    getRowId,
    initialState: { sorting: initialSorting ?? [] },
  });

  const rowHeight = activeDensity === "compact" ? "h-9" : "h-11";
  const interactive = Boolean(rowHref ?? onRowClick);

  const open = (row: T) => {
    if (onRowClick) onRowClick(row);
    else if (rowHref) router.push(rowHref(row) as Route);
  };
  const onRowMouse = (event: MouseEvent<HTMLElement>, row: T) => {
    if ((event.target as HTMLElement).closest("a,button")) return;
    open(row);
  };
  const onRowKey = (event: KeyboardEvent<HTMLElement>, row: T) => {
    if (event.key === "Enter" && event.target === event.currentTarget) open(row);
  };

  const hideable = table.getAllLeafColumns().filter((column) => column.getCanHide());
  const rows = table.getRowModel().rows;
  const showToolbar = enableColumnVisibility && hideable.length > 1;

  return (
    <div data-slot="data-table" className="min-w-0 overflow-x-auto rounded-2xl border border-line-strong bg-surface-1/70 backdrop-blur-[14px]">
      <div className="flex items-center justify-end gap-2 border-b px-3 py-1.5">
        <Button
          variant="ghost"
          size="xs"
          onClick={() => {
            setDensity(activeDensity === "compact" ? "comfortable" : "compact");
          }}
        >
          {activeDensity === "compact" ? "Comfortable rows" : "Compact rows"}
        </Button>
        {showToolbar ? (
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="xs" />}>
              <Columns3Icon /> Columns
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              {hideable.map((column) => (
                <DropdownMenuCheckboxItem
                  key={column.id}
                  checked={column.getIsVisible()}
                  onCheckedChange={(visible) => column.toggleVisibility(visible)}
                >
                  {typeof column.columnDef.header === "string" ? column.columnDef.header : column.id}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
      <Table className="text-[13px]">
        {caption ? <TableCaption className="sr-only">{caption}</TableCaption> : null}
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id}>
              {group.headers.map((header) => {
                const sorted = header.column.getIsSorted();
                const canSort = header.column.getCanSort();
                return (
                  <TableHead
                    key={header.id}
                    aria-sort={
                      sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined
                    }
                    className={cn(
                      "h-auto px-3 py-2 font-mono text-label font-medium uppercase tracking-[0.06em] text-muted-foreground",
                      header.column.columnDef.meta?.align === "right" && "text-right",
                    )}
                  >
                    {header.isPlaceholder ? null : canSort ? (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 hover:text-foreground"
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        <table.FlexRender header={header} />
                        {sorted === "asc" ? (
                          <ArrowUpIcon className="size-3" />
                        ) : sorted === "desc" ? (
                          <ArrowDownIcon className="size-3" />
                        ) : (
                          <ArrowUpDownIcon className="size-3 opacity-50" />
                        )}
                      </button>
                    ) : (
                      <table.FlexRender header={header} />
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {loading
            ? Array.from({ length: 10 }, (_, index) => (
                <TableRow key={`skeleton-${index}`} className={rowHeight}>
                  {table.getVisibleLeafColumns().map((column) => (
                    <TableCell key={column.id}>
                      <Skeleton className="h-4 w-full max-w-32" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            : rows.map((row) => (
                <TableRow
                  key={row.id}
                  className={cn(
                    rowHeight,
                    interactive && "cursor-pointer",
                    row.id === selectedRowId && "bg-brand-soft",
                  )}
                  aria-selected={selectedRowId === undefined ? undefined : row.id === selectedRowId}
                  tabIndex={interactive ? 0 : undefined}
                  onClick={interactive ? (event) => onRowMouse(event, row.original) : undefined}
                  onKeyDown={interactive ? (event) => onRowKey(event, row.original) : undefined}
                >
                  {row.getVisibleCells().map((cell, index) => (
                    <TableCell
                      key={cell.id}
                      className={cn(
                        "whitespace-nowrap px-3 py-2.5",
                        cell.column.columnDef.meta?.align === "right" && "text-right",
                        cell.column.columnDef.meta?.mono && "font-mono tabular-nums",
                      )}
                    >
                      {index === 0 && rowHref ? (
                        <Link href={rowHref(row.original) as Route} className="hover:underline">
                          <table.FlexRender cell={cell} />
                        </Link>
                      ) : (
                        <table.FlexRender cell={cell} />
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
        </TableBody>
      </Table>
      {!loading && rows.length === 0 ? (
        <div className="p-4">{emptyState ?? <p className="text-sm text-muted-foreground">No rows.</p>}</div>
      ) : null}
      {pagination ? <PageControls pagination={pagination} /> : null}
    </div>
  );
}
