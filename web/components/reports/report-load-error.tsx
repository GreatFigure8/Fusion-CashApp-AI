"use client";

import { useRouter } from "next/navigation";
import type * as React from "react";

import { ErrorAlert } from "@/components/common/error-alert";
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
  return <ErrorAlert error={error} title={title} onRetry={() => router.refresh()} />;
}
