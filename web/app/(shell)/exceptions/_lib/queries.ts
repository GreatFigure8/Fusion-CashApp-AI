import "server-only";

import { cache } from "react";

import { api } from "@/lib/api/client";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import type { Result } from "@/lib/result";

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
