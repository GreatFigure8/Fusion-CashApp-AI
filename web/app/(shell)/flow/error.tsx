"use client";

import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";

export default function FlowError({ reset }: { error: Error; reset: () => void }) {
  // The message is never shown: it could carry remittance content.
  return (
    <StateCard
      kind="error"
      headline="Couldn't load the flow"
      body="Something went wrong."
      actions={
        <Button size="sm" variant="outline" onClick={reset}>
          Retry
        </Button>
      }
    />
  );
}
