"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Meter } from "@/components/common/meter";
import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";
import { replayProgressEvent, type ReplayProgressEvent } from "@/lib/lab/schemas";
import { useEventStream } from "@/hooks/use-event-stream";

const TERMINAL_EVENTS = new Set(["done", "failed"]);

/** A running replay: "N of M items" over the replay stream; the page re-reads when it ends. */
export function ReplayProgress({
  replayId,
  done: initialDone,
  total: initialTotal,
}: {
  replayId: string;
  done: number;
  total: number;
}) {
  const router = useRouter();
  const [progress, setProgress] = useState({ done: initialDone, total: initialTotal });
  const { status, retry } = useEventStream<ReplayProgressEvent>(`/lab/replays/${replayId}/stream`, {
    schema: replayProgressEvent,
    onEvent: ({ event, data }) => {
      setProgress((p) => ({ done: data.done ?? p.done, total: data.total ?? p.total }));
      const ended = TERMINAL_EVENTS.has(event) || (data.status !== undefined && data.status !== "RUNNING");
      if (ended) router.refresh();
    },
  });

  return (
    <StateCard
      kind="loading"
      label="Loading · replay"
      headline="Replaying the candidate"
      body={
        status === "live" ? undefined : status === "reconnecting" ? "Reconnecting…" : "Disconnected."
      }
      actions={
        status === "disconnected" ? (
          <Button variant="outline" onClick={retry}>
            Retry
          </Button>
        ) : null
      }
    >
      <Meter value={progress.done} max={progress.total} label="Replay progress" />
      <p className="font-mono text-xs text-muted-foreground">
        {progress.done} of {progress.total} items
      </p>
    </StateCard>
  );
}
