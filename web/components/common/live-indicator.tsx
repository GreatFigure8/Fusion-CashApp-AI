"use client";

import { LiveDot } from "@/components/common/live-dot";
import { Pill } from "@/components/common/pill";
import { Button } from "@/components/ui/button";
import type { StreamStatus } from "@/lib/api/use-event-stream";

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
  const tone = status === "live" ? "ok" : status === "reconnecting" ? "warn" : "err";
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
      className="flex items-center gap-2 text-xs"
    >
      <Pill tone={tone}>
        <LiveDot tone={tone} pulse={status === "live"} />
        {label}
      </Pill>
      {status === "disconnected" ? (
        <Button variant="outline" size="xs" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}
