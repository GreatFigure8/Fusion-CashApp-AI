"use client";

import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";

export default function DashboardError({ reset }: { error: Error; reset: () => void }) {
  return (
    <StateCard
      kind="error"
      headline="Couldn't load the aggregates"
      body="Something went wrong while reading the progress figures."
      actions={
        <Button variant="outline" size="sm" onClick={reset}>
          Retry
        </Button>
      }
    />
  );
}
