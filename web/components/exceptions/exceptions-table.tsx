"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import { DataTable } from "@/components/common/data-table";
import type { Schemas } from "@/lib/api/types";

import { buildExceptionColumns } from "./exception-columns";
import { NoExceptions, NoMatches } from "./empty-states";

type Props = Readonly<{
  list: Schemas["ExceptionListOut"];
  filtered: boolean;
  canWork: boolean;
}>;

export function ExceptionsTable({ list, filtered, canWork }: Props): React.JSX.Element {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // A row click sets ?item=WI-n and keeps every filter.
  const hrefFor = (params: URLSearchParams) => {
    const query = params.toString();
    return query ? `${pathname}?${query}` : pathname;
  };
  const open = useCallback(
    (id: number) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("item", `WI-${id}`);
      const query = params.toString();
      router.push((query ? `${pathname}?${query}` : pathname) as Route, { scroll: false });
    },
    [router, pathname, searchParams],
  );
  const hrefForPage = (page: number) => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("item");
    if (page <= 1) params.delete("page");
    else params.set("page", String(page));
    return hrefFor(params);
  };
  const clearHref = pathname;

  const columns = useMemo(() => buildExceptionColumns({ canWork, onOpen: open }), [canWork, open]);

  return (
    <DataTable
      columns={columns}
      data={list.items}
      getRowId={(row) => String(row.id)}
      onRowClick={(row) => open(row.id)}
      pagination={{
        page: list.page,
        pageSize: list.page_size,
        total: list.total,
        hrefForPage,
      }}
      enableColumnVisibility={false}
      densityStorageKey="exceptions-density"
      emptyState={filtered ? <NoMatches clearHref={clearHref} /> : <NoExceptions />}
      caption="Exceptions"
    />
  );
}
