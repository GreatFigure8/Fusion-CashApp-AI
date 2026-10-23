import "server-only";

import { cache } from "react";

import { api } from "@/lib/api/client";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import type { Result } from "@/lib/result";

import {
  chipFilters,
  EXCEPTION_CHIPS,
  type ChipId,
} from "@/components/exceptions/filter-chips";

import { filtersToSearchParams, type ExceptionFilters } from "./search-params";

export const PAGE_SIZE = 50;

const listByQuery = cache(
  async (query: string): Promise<Result<Schemas["ExceptionListOut"], ApiError>> => {
    const params = new URLSearchParams(query);
    params.set("page_size", String(PAGE_SIZE));
    params.delete("item");
    return api("get", "/exceptions", { query: params as never });
  },
);

export function getExceptions(
  filters: ExceptionFilters,
): Promise<Result<Schemas["ExceptionListOut"], ApiError>> {
  return listByQuery(filtersToSearchParams(filters).toString());
}

const totalByQuery = cache(async (query: string): Promise<number | undefined> => {
  const params = new URLSearchParams(query);
  params.set("page_size", "1");
  params.delete("item");
  params.delete("page");
  const result = await api("get", "/exceptions", { query: params as never });
  return result.ok ? result.value.total : undefined;
});

export type ExceptionCounts = Readonly<{
  chips: Partial<Record<ChipId, number>>;
  /** Applied items hidden by the default view; null when it can't be worked out. */
  appliedHidden: number | null;
}>;

/**
 * Totals for every filter chip (other filters kept) and the count of hidden applied items.
 * The calls run together; a failed call leaves its key out and never fails the page.
 */
export async function getExceptionCounts(filters: ExceptionFilters): Promise<ExceptionCounts> {
  const [entries, shown, all] = await Promise.all([
    Promise.all(
      EXCEPTION_CHIPS.map(async (chip) => {
        const query = filtersToSearchParams(chipFilters(filters, chip.id)).toString();
        return [chip.id, await totalByQuery(query)] as const;
      }),
    ),
    totalByQuery(filtersToSearchParams({ ...filters, includeAutoApplied: false }).toString()),
    totalByQuery(filtersToSearchParams({ ...filters, includeAutoApplied: true }).toString()),
  ]);
  const chips: Partial<Record<ChipId, number>> = {};
  for (const [id, total] of entries) if (total !== undefined) chips[id] = total;

  const appliedHidden = shown !== undefined && all !== undefined ? Math.max(0, all - shown) : null;
  return { chips, appliedHidden };
}

export const getItemDetail = cache(
  (itemId: number): Promise<Result<Schemas["ItemDetailOut"], ApiError>> =>
    api("get", "/items/{item_id}", { params: { item_id: itemId } }),
);

export const getItemHistory = cache(
  (itemId: number): Promise<Result<Schemas["HistoryOut"], ApiError>> =>
    api("get", "/items/{item_id}/history", { params: { item_id: itemId } }),
);

export const getFusionContext = cache(
  (itemId: number): Promise<Result<Schemas["FusionContextOut"], ApiError>> =>
    api("get", "/items/{item_id}/fusion-context", { params: { item_id: itemId } }),
);

export const getMe = cache(
  (): Promise<Result<Schemas["MeResponse"], ApiError>> => api("get", "/me"),
);
