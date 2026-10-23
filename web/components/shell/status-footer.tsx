"use client";

import { useState } from "react";

import { GlassPanel } from "@/components/common/glass-panel";
import { Pill } from "@/components/common/pill";
import { useEventStream, type StreamEvent } from "@/hooks/use-event-stream";
import { engineStatusSchema, formatFooter, type EngineStatus } from "@/lib/engine/status";

/**
 * The bus strip under the page. Starts from the server-side `/engine/status` read and follows
 * the `status` events of `/engine/stream`. With neither, it says so and the page still works.
 */
export function StatusFooter({
  initial,
  pending = false,
}: {
  initial: EngineStatus | null;
  pending?: boolean;
}) {
  const [status, setStatus] = useState<EngineStatus | null>(initial);

  useEventStream<EngineStatus>("/engine/stream", {
    schema: engineStatusSchema,
    enabled: !pending,
    onEvent: (frame: StreamEvent<EngineStatus>) => {
      if (frame.event === "status") setStatus(frame.data);
    },
  });

  const view = status ? formatFooter(status) : null;
  return (
    <GlassPanel
      as="footer"
      aria-label="Bus status"
      className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-2 text-xs text-muted-foreground"
    >
      {view ? (
        <>
          <Pill tone={view.healthy ? "ok" : "err"} dot>
            {view.healthy ? "Bus healthy" : "Bus unhealthy"}
          </Pill>
          <span className="font-mono">lag {view.lag}</span>
          <span className={view.dlq > 0 ? "font-mono text-warn-ink" : "font-mono"}>
            dlq {view.dlq}
          </span>
          <span>{view.pollers}</span>
          <span className="ml-auto font-mono">{view.region}</span>
        </>
      ) : (
        <span>{pending ? "Reading bus status…" : "Bus status unavailable"}</span>
      )}
    </GlassPanel>
  );
}
