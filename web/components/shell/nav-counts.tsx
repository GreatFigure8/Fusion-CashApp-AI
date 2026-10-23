"use client";

import { useReviewOpenCount } from "@/components/review/nav-count";
import { useFlowStream } from "@/components/shell/flow-stream";
import type { NavCountSource } from "@/components/shell/nav";

export type NavCountHook = () => number | null;

function useInFlight(): number | null {
  const { summary } = useFlowStream();
  if (!summary) return null;
  return summary.stages.reduce((total, tile) => total + tile.in_queue + tile.in_progress, 0);
}

function useOpenExceptions(): number | null {
  const { summary } = useFlowStream();
  return summary?.kpis.needs_person ?? null;
}

/** Placeholder for counts whose owning story has not landed; renders nothing. */
function useNoCount(): number | null {
  return null;
}

/** One hook per count source; `lab.candidates` stays empty until the matching lab UI lands. */
export const NAV_COUNT_SOURCES: Readonly<Record<NavCountSource, NavCountHook>> = {
  "flow.in_flight": useInFlight,
  "exceptions.open": useOpenExceptions,
  "review.queue": useReviewOpenCount,
  "lab.candidates": useNoCount,
};

/** The right-aligned mono count of a nav item, or nothing while the source has no value. */
export function NavCount({ source, testId }: { source: NavCountSource; testId?: string }) {
  const count = NAV_COUNT_SOURCES[source]();
  if (count === null) return null;
  return (
    <span
      data-testid={testId}
      className="ml-auto font-mono text-label tabular-nums text-faint"
    >
      {count}
    </span>
  );
}
