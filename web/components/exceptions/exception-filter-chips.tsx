"use client";

import type { Route } from "next";
import { usePathname, useRouter } from "next/navigation";

import {
  filtersToSearchParams,
  type ExceptionFilters,
} from "@/app/(shell)/exceptions/_lib/search-params";
import { FilterChip } from "@/components/common/filter-chip";

import { activeChip, chipFilters, EXCEPTION_CHIPS, type ChipId } from "./filter-chips";

/** The chip row: presets over the URL filters, each with the count the list query returned. */
export function ExceptionFilterChips({
  filters,
  counts,
}: Readonly<{
  filters: ExceptionFilters;
  counts: Partial<Record<ChipId, number>>;
}>): React.JSX.Element {
  const router = useRouter();
  const pathname = usePathname();
  const active = activeChip(filters);

  return (
    <div role="group" aria-label="Filter by reason" className="flex flex-wrap gap-2">
      {EXCEPTION_CHIPS.map((chip) => (
        <FilterChip
          key={chip.id}
          active={active === chip.id}
          count={counts[chip.id]}
          onClick={() => {
            const query = filtersToSearchParams(chipFilters(filters, chip.id)).toString();
            router.push((query ? `${pathname}?${query}` : pathname) as Route, { scroll: false });
          }}
        >
          {chip.label}
        </FilterChip>
      ))}
    </div>
  );
}
