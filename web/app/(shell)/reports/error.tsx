"use client";

import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";

export default function ReportsError({ reset }: { error: Error; reset: () => void }) {
  return (
    <StateCard
      kind="error"
      label="Error · reports"
      headline="Couldn't show the reports"
      body="Something went wrong while showing the reports."
      actions={
        <Button variant="outline" size="sm" onClick={reset}>
          Retry
        </Button>
      }
    />
  );
}
