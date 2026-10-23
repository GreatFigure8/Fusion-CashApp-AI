"use client";

import { PauseIcon } from "lucide-react";
import { useTransition } from "react";
import { toast } from "sonner";

import { pauseBacklogBatch } from "@/app/(shell)/flow/actions";
import { GlassPanel } from "@/components/common/glass-panel";
import { Meter } from "@/components/common/meter";
import { Button } from "@/components/ui/button";
import type { Schemas } from "@/lib/api/types";

/** "Backlog batch B-0007 · 2,140 / 5,000 items · ETA 41 min", with Pause for backlog:run. */
export function BacklogBar({
  batch,
  canPause,
}: {
  batch: Schemas["BacklogProgressOut"];
  canPause: boolean;
}) {
  const [pending, startTransition] = useTransition();
  const eta = batch.eta_minutes === null ? "" : ` · ETA ${batch.eta_minutes} min`;
  const text = `Backlog batch ${batch.name} · ${batch.processed.toLocaleString("en-US")} / ${batch.total.toLocaleString("en-US")} items${eta}`;

  return (
    <GlassPanel
      as="div"
      className="flex w-full flex-col gap-2 p-3 sm:flex-row sm:items-center"
    >
      <div data-slot="backlog-bar" className="flex min-w-0 flex-1 flex-col gap-2">
        <span className="text-sm">{text}</span>
        <Meter value={batch.processed} max={batch.total} size={5} tone="accent" label={text} />
      </div>
      {canPause ? (
        <Button
          variant="outline"
          size="sm"
          disabled={pending}
          onClick={() =>
            startTransition(async () => {
              const result = await pauseBacklogBatch(batch.id);
              if (!result.ok) toast.error(`Couldn't pause the batch. ${result.error.message}`);
              else toast.success(`Paused ${batch.name}`);
            })
          }
        >
          <PauseIcon /> Pause
        </Button>
      ) : null}
    </GlassPanel>
  );
}
