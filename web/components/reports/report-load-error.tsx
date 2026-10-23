"use client";

import { useRouter } from "next/navigation";
import type * as React from "react";

import { describeError } from "@/components/common/error-alert";
import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api/errors";

/** A failed report load, with Retry re-rendering the same URL. */
export function ReportLoadError({
  error,
  title,
}: {
  error: ApiError;
  title: string;
}): React.JSX.Element {
  const router = useRouter();
  return (
    <StateCard
      kind="error"
      headline={title}
      body={describeError(error)}
      actions={
        <Button variant="outline" size="sm" onClick={() => router.refresh()}>
          Retry
        </Button>
      }
    />
  );
}
