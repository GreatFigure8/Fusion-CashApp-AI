"use client";

import { ErrorAlert } from "@/components/common/error-alert";
import { apiError } from "@/lib/api/errors";

export default function AssistantError({ reset }: { error: Error; reset: () => void }) {
  // The message is never shown: it could carry remittance content.
  return (
    <ErrorAlert
      error={apiError(500, "internal_error", "Something went wrong.", null)}
      title="Couldn't load the assistant"
      onRetry={reset}
    />
  );
}
