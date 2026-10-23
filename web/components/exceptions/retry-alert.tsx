"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { ErrorAlert } from "@/components/common/error-alert";
import type { ApiError } from "@/lib/api/errors";

/** An `ErrorAlert` whose Retry re-runs the server render of the current page. */
export function RetryAlert({
  error,
  title,
}: Readonly<{ error: ApiError; title: string }>): React.JSX.Element {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <ErrorAlert
      error={error}
      title={title}
      retrying={pending}
      onRetry={() => startTransition(() => router.refresh())}
    />
  );
}
