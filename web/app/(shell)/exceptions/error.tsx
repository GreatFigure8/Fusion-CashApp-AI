"use client";

import { ErrorAlert } from "@/components/common/error-alert";
import { apiError } from "@/lib/api/errors";

export default function ExceptionsError({
  error,
  reset,
}: Readonly<{ error: Error & { digest?: string }; reset: () => void }>) {
  return (
    <ErrorAlert
      title="Couldn't load the exceptions"
      error={apiError(500, "internal_error", "Something went wrong.", error.digest ?? null)}
      onRetry={reset}
    />
  );
}
