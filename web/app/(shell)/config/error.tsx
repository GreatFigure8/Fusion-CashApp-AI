"use client";

import { Button } from "@/components/ui/button";

/** Unexpected render errors only. Expected API errors render through ErrorAlert in place. */
export default function ConfigError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div role="alert" className="space-y-3 rounded-xl border border-destructive/40 p-4">
      <h2 className="text-sm font-semibold">Something went wrong</h2>
      <p className="text-sm text-muted-foreground">
        The configuration page couldn&apos;t be shown.
        {error.digest ? ` Reference: ${error.digest}` : ""}
      </p>
      <Button type="button" variant="outline" onClick={reset}>
        Retry
      </Button>
    </div>
  );
}
