"use client";

import { ActionButton } from "@/components/common/action-button";
import { StateCard } from "@/components/common/state-card";

export default function EngineError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="p-4">
      <StateCard
        kind="error"
        label="Error · engine"
        headline="Couldn't load the engine"
        body="Try again in a moment."
        actions={
          <ActionButton variant="outline" onClick={() => reset()}>
            Retry
          </ActionButton>
        }
      />
    </div>
  );
}
