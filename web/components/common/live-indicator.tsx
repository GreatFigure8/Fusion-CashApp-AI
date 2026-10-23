"use client";

import { Button } from "@/components/ui/button";
import type { StreamStatus } from "@/hooks/use-event-stream";
import { cn } from "@/lib/utils";

/** The stream's connection state: Live, Reconnecting with the retry count, or Disconnected. */
export function LiveIndicator({
  status,
  retries,
  onRetry,
}: {
  status: StreamStatus;
  retries: number;
  onRetry: () => void;
}) {
  const dot =
    status === "live"
      ? "bg-status-success"
      : status === "reconnecting"
        ? "bg-status-waiting"
        : "bg-status-error";
  const label =
    status === "live"
      ? "Live"
      : status === "reconnecting"
        ? retries > 0
          ? `Reconnecting… (retry ${retries})`
          : "Reconnecting…"
        : "Disconnected — data may be stale";
  return (
    <div
      data-slot="live-indicator"
      data-status={status}
      role="status"
      className="flex flex-col gap-1.5 px-2 text-xs"
    >
      <span className="flex items-center gap-2">
        <span aria-hidden className={cn("size-2 shrink-0 rounded-full", dot)} />
        <span className="group-data-[collapsible=icon]:sr-only">{label}</span>
      </span>
      {status === "disconnected" ? (
        <Button
          variant="outline"
          size="xs"
          onClick={onRetry}
          className="group-data-[collapsible=icon]:hidden"
        >
          Retry
        </Button>
      ) : null}
    </div>
  );
}
