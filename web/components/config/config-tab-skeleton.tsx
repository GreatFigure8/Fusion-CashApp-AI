import { Skeleton } from "@/components/ui/skeleton";

import type { ConfigTabId } from "./config-registry";

/** Loading state for a tab: a table for aliases, rows for everything else. */
export function ConfigTabSkeleton({ tab }: { tab: ConfigTabId }) {
  if (tab === "aliases") {
    return (
      <div data-testid="config-tab-skeleton" className="space-y-2" aria-busy="true">
        <Skeleton className="h-9 w-72" />
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }
  return (
    <div data-testid="config-tab-skeleton" className="space-y-4" aria-busy="true">
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="space-y-2 rounded-xl border p-4">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-3 w-80 max-w-full" />
          <Skeleton className="h-9 w-40" />
        </div>
      ))}
    </div>
  );
}
