"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import { MonoLabel } from "@/components/common/mono-label";
import { TopBar } from "@/components/shell/top-bar";
import { useEventStream } from "@/hooks/use-event-stream";
import type { Schemas } from "@/lib/api/types";
import { engineStatusEventSchema } from "@/lib/engine/schemas";
import { controlsEnabled, secondsAgo, type EngineAction } from "@/lib/engine/view";

import { AuditList } from "./audit-list";
import { DlqTable } from "./dlq-table";
import { EngineActionDialog, type EngineActionResult } from "./engine-action-dialog";
import { BusUnavailable, OperatorBanner } from "./engine-states";
import { EngineTopPills } from "./engine-top-pills";
import { ReplayResult } from "./replay-result";
import { StationsPanel } from "./stations-panel";
import { ThrottlePanel } from "./throttle-panel";

type Props = Readonly<{
  status: Schemas["EngineStatusOut"];
  deadLetters: Schemas["DeadLetterPage"];
  audit: Schemas["EngineAuditPage"];
  /** null when the MCP status could not be read. */
  mcp: Schemas["McpStatusOut"] | null;
  canControl: boolean;
}>;

function throttleValues(t: Schemas["EngineStatusOut"]["throttle"]) {
  const perStage = t.per_stage["*"] ?? Object.values(t.per_stage)[0] ?? 1;
  return { perStage, applyPerReceipt: t.apply_per_receipt };
}

export function EngineBoard({ status: initial, deadLetters, audit, mcp, canControl }: Props) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [live, setLive] = useState<{ status: Schemas["EngineStatusOut"]; at: number | null }>({
    status: initial,
    at: null, // null = the server read; counted from the first tick
  });
  const [now, setNow] = useState<number | null>(null);
  const [action, setAction] = useState<EngineAction | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [replay, setReplay] = useState<{
    result: Schemas["ReplayOut"];
    ids: string[];
  } | null>(null);

  // A fresh server read (after router.refresh) replaces the live copy.
  const [seenInitial, setSeenInitial] = useState(initial);
  if (seenInitial !== initial) {
    setSeenInitial(initial);
    setLive({ status: initial, at: null });
  }

  const stream = useEventStream<Schemas["EngineStatusOut"]>("/engine/stream", {
    schema: engineStatusEventSchema,
    onEvent: (e) => {
      if (e.event === "status") setLive({ status: e.data, at: Date.now() });
    },
  });

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const status = live.status;
  const enabled = controlsEnabled({ canControl, busHealthy: status.bus_healthy });

  const done = (r: EngineActionResult) => {
    if (r.kind === "status") setLive({ status: r.status, at: Date.now() });
    else if (action?.kind === "replay") {
      setReplay({ result: r.result, ids: action.eventIds });
      setSelected(new Set());
    }
    startTransition(() => router.refresh());
  };

  const retry = () => {
    stream.retry();
    startTransition(() => router.refresh());
  };

  return (
    <>
      <TopBar
        title="Engine"
        pills={<EngineTopPills updatedSecondsAgo={secondsAgo(live.at ?? now ?? 0, now ?? 0)} mcp={mcp} />}
      >
        <MonoLabel>OCI Streaming · group {status.consumer_group}</MonoLabel>
      </TopBar>
      <div className="grid gap-4 p-4">
        {!canControl ? <OperatorBanner /> : null}
        {!status.bus_healthy ? <BusUnavailable onRetry={retry} /> : null}
        <StationsPanel
          stations={status.stations}
          enabled={enabled}
          canControl={canControl}
          onAction={(kind, station) => setAction({ kind, station })}
        />
        <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(340px,1fr))]">
          <ThrottlePanel
            initial={throttleValues(status.throttle)}
            configVersion={status.config_version}
            enabled={enabled}
            canControl={canControl}
            onSave={(v) =>
              setAction({ kind: "throttle", perStage: v.perStage, applyPerReceipt: v.applyPerReceipt })
            }
          />
          <AuditList rows={audit.items} />
        </div>
        <DlqTable
          rows={deadLetters.items}
          total={status.dlq_total}
          selected={selected}
          onSelectedChange={setSelected}
          enabled={enabled}
          canControl={canControl}
          onReplay={() => setAction({ kind: "replay", eventIds: [...selected] })}
        />
        {replay ? <ReplayResult result={replay.result} replayedIds={replay.ids} /> : null}
      </div>
      <EngineActionDialog
        action={action}
        status={status}
        onClose={() => setAction(null)}
        onDone={done}
      />
    </>
  );
}
