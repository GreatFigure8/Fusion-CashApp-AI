"use client";

import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";

/** Unexpected render errors only. Expected API errors render through ErrorAlert in place. */
export default function ConfigError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <StateCard
      kind="error"
      label="Error · settings"
      headline="Something went wrong"
      body={`The settings page couldn't be shown.${error.digest ? ` Reference: ${error.digest}` : ""}`}
      actions={
        <Button type="button" variant="outline" onClick={retry}>
          Try again
        </Button>
      }
    />
  );
}
