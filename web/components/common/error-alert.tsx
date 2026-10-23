"use client";

import { CopyIcon, TriangleAlertIcon } from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api/errors";

export function describeError(error: ApiError): string {
  if (error.status === 0) return "The API couldn't be reached.";
  const id = error.requestId ? ` (request id ${error.requestId.slice(0, 8)}…)` : "";
  return `The API returned ${error.status}${id}.`;
}

/** Renders the API's single error shape: status, short request id and an optional Retry. */
export function ErrorAlert({
  error,
  title,
  onRetry,
  retrying = false,
}: {
  error: ApiError;
  title: string;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  const requestId = error.requestId;
  return (
    <Alert variant="destructive" data-slot="error-alert">
      <TriangleAlertIcon aria-hidden />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <span title={requestId ?? undefined}>{describeError(error)}</span>
      </AlertDescription>
      <AlertAction className="flex items-center gap-1">
        {requestId ? (
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="Copy request id"
            onClick={() => {
              void navigator.clipboard
                .writeText(requestId)
                .then(() => toast.success("Request id copied"))
                .catch(() => toast.error("Couldn't copy the request id"));
            }}
          >
            <CopyIcon />
          </Button>
        ) : null}
        {onRetry ? (
          <Button variant="outline" size="xs" onClick={onRetry} disabled={retrying}>
            {retrying ? "Retrying…" : "Retry"}
          </Button>
        ) : null}
      </AlertAction>
    </Alert>
  );
}
