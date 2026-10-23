"use client";

import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";
import { formatClockShort } from "@/lib/metrics/format";

/** The error state when last-good data exists: the tiles stay, marked stale, with a Retry. */
export function StaleBanner({ asOf, onRetry }: { asOf: string; onRetry: () => void }) {
  return (
    <StateCard
      kind="error"
      headline="Couldn't load the aggregates"
      body={`Tiles show values from ${formatClockShort(asOf)} UTC and are marked stale.`}
      actions={
        <Button variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      }
    />
  );
}
