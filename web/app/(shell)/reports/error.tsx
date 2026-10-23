"use client";

import { ErrorAlert } from "@/components/common/error-alert";

export default function ReportsError({ reset }: { error: Error; reset: () => void }) {
  return (
    <ErrorAlert
      error={{
        status: 500,
        code: "internal_error",
        message: "Something went wrong while showing the reports.",
        requestId: null,
        details: [],
      }}
      title="Couldn't show the reports"
      onRetry={reset}
    />
  );
}
