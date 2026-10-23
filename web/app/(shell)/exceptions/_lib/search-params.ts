import { z } from "zod";

import type { QueryOf, Schemas } from "@/lib/api/types";

/** Pure and client-safe: the URL is the filter state, shared by the server page and the filter bar. */

export type ErrorCode = Schemas["ErrorCode"];
export type Stage = Schemas["Stage"];
export type ExceptionSort = NonNullable<QueryOf<"/exceptions", "get">["sort"]>;

export const EXCEPTION_SORTS = [
  "age",
  "-age",
  "amount",
  "-amount",
  "payment_date",
  "-payment_date",
  "id",
  "-id",
] as const satisfies readonly ExceptionSort[];

// Drift check: a sort added to the API without being added here fails type-checking.
type MissingSort = Exclude<ExceptionSort, (typeof EXCEPTION_SORTS)[number]>;
const sortListIsComplete: [MissingSort] extends [never] ? true : never = true;
void sortListIsComplete;

export const DEFAULT_SORT: ExceptionSort = "-age";

export type ExceptionFilters = Readonly<{
  q?: string;
  amountMin?: string;
  amountMax?: string;
  dateFrom?: string;
  dateTo?: string;
  errorCodes: readonly ErrorCode[];
  stage?: Stage;
  lockedByMe: boolean;
  includeAutoApplied: boolean;
  includeArchived: boolean;
  page: number;
  sort: ExceptionSort;
  item?: `WI-${number}`;
}>;

export const DEFAULT_FILTERS: ExceptionFilters = Object.freeze({
  errorCodes: [],
  lockedByMe: false,
  includeAutoApplied: false,
  includeArchived: false,
  page: 1,
  sort: DEFAULT_SORT,
});

const MONEY = /^-?\d+(\.\d{1,2})?$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const CODE = /^[A-Z][A-Z0-9_]*$/;
const WORK_ITEM = /^WI-\d+$/;

// Every field falls back to its default instead of failing the page: a hand-edited URL never throws.
const text = z.string().trim().min(1).max(200).optional().catch(undefined);
const money = z.string().trim().regex(MONEY).optional().catch(undefined);
const isoDate = z.string().regex(ISO_DATE).optional().catch(undefined);
const flag = z
  .enum(["1", "true", "0", "false"])
  .transform((v) => v === "1" || v === "true")
  .catch(false);

const first = (value: unknown): unknown => (Array.isArray(value) ? value[0] : value);
const many = (value: unknown): unknown[] =>
  value === undefined ? [] : Array.isArray(value) ? value : [value];

export const exceptionFiltersSchema: z.ZodType<ExceptionFilters, Record<string, unknown>> = z
  .object({
    q: z.preprocess(first, text),
    amount_min: z.preprocess(first, money),
    amount_max: z.preprocess(first, money),
    date_from: z.preprocess(first, isoDate),
    date_to: z.preprocess(first, isoDate),
    error_codes: z.preprocess(
      many,
      z
        .array(z.unknown())
        .transform((values) => {
          const seen = new Set<ErrorCode>();
          for (const v of values) {
            if (typeof v === "string" && CODE.test(v)) seen.add(v as ErrorCode);
          }
          return [...seen];
        })
        .catch([]),
    ),
    stage: z.preprocess(
      first,
      z
        .string()
        .regex(CODE)
        .transform((v) => v as Stage)
        .optional()
        .catch(undefined),
    ),
    locked_by_me: z.preprocess(first, flag),
    include_auto_applied: z.preprocess(first, flag),
    include_archived: z.preprocess(first, flag),
    page: z.preprocess(first, z.coerce.number().int().min(1).max(100_000).catch(1)),
    sort: z.preprocess(first, z.enum(EXCEPTION_SORTS).catch(DEFAULT_SORT)),
    item: z.preprocess(
      first,
      z
        .string()
        .regex(WORK_ITEM)
        .transform((v) => v as `WI-${number}`)
        .optional()
        .catch(undefined),
    ),
  })
  .transform(
    (v): ExceptionFilters => ({
      q: v.q,
      amountMin: v.amount_min,
      amountMax: v.amount_max,
      dateFrom: v.date_from,
      dateTo: v.date_to,
      errorCodes: v.error_codes,
      stage: v.stage,
      lockedByMe: v.locked_by_me,
      includeAutoApplied: v.include_auto_applied,
      includeArchived: v.include_archived,
      page: v.page,
      sort: v.sort,
      item: v.item,
    }),
  );

export function parseExceptionFilters(
  sp: Record<string, string | string[] | undefined>,
): ExceptionFilters {
  return exceptionFiltersSchema.parse(sp);
}

/** Defaults are omitted, so a default view has a clean URL. Round-trips with `parseExceptionFilters`. */
export function filtersToSearchParams(f: ExceptionFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (f.q) params.set("q", f.q);
  if (f.amountMin) params.set("amount_min", f.amountMin);
  if (f.amountMax) params.set("amount_max", f.amountMax);
  if (f.dateFrom) params.set("date_from", f.dateFrom);
  if (f.dateTo) params.set("date_to", f.dateTo);
  for (const code of f.errorCodes) params.append("error_codes", code);
  if (f.stage) params.set("stage", f.stage);
  if (f.lockedByMe) params.set("locked_by_me", "1");
  if (f.includeAutoApplied) params.set("include_auto_applied", "1");
  if (f.includeArchived) params.set("include_archived", "1");
  if (f.page !== DEFAULT_FILTERS.page) params.set("page", String(f.page));
  if (f.sort !== DEFAULT_SORT) params.set("sort", f.sort);
  if (f.item) params.set("item", f.item);
  return params;
}

/** True when any filter narrows the list (paging, sorting and the open item don't count). */
export function isFiltered(f: ExceptionFilters): boolean {
  return Boolean(
    f.q ||
    f.amountMin ||
    f.amountMax ||
    f.dateFrom ||
    f.dateTo ||
    f.errorCodes.length > 0 ||
    f.stage ||
    f.lockedByMe ||
    f.includeAutoApplied ||
    f.includeArchived,
  );
}

export function parseWorkItemParam(item: string | undefined): number | null {
  if (!item || !WORK_ITEM.test(item)) return null;
  return Number(item.slice(3));
}
