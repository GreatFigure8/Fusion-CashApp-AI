"use client";

import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";

export default function LabError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // The message is never shown: it could carry remittance content.
  return (
    <StateCard
      kind="error"
      label="Error · lab"
      headline="Couldn't load the lab"
      body={
        <>
          Something went wrong.
          {error.digest ? <span className="font-mono"> Reference {error.digest}.</span> : null}
        </>
      }
      actions={
        <Button variant="outline" onClick={reset}>
          Retry
        </Button>
      }
    />
  );
}
