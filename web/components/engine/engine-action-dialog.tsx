"use client";

import { useState } from "react";

import {
  drainStationAction,
  pauseStationAction,
  replayDeadLettersAction,
  resumeStationAction,
  setThrottleAction,
} from "@/app/(shell)/engine/_lib/actions";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import type { Result } from "@/lib/result";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import { copyFor, CONFLICT_MESSAGE, type EngineAction } from "@/lib/engine/view";

export type EngineActionResult =
  | { kind: "replay"; result: Schemas["ReplayOut"] }
  | { kind: "status"; status: Schemas["EngineStatusOut"] };

async function run(
  action: EngineAction,
  reason: string,
  expectedVersion: number,
): Promise<Result<EngineActionResult, ApiError>> {
  switch (action.kind) {
    case "pause":
    case "resume":
    case "drain": {
      const fn =
        action.kind === "pause"
          ? pauseStationAction
          : action.kind === "resume"
            ? resumeStationAction
            : drainStationAction;
      const r = await fn({ station: action.station, reason, expectedVersion });
      return r.ok ? { ok: true, value: { kind: "status", status: r.value.status } } : r;
    }
    case "throttle": {
      const r = await setThrottleAction({
        perStage: action.perStage,
        applyPerReceipt: action.applyPerReceipt,
        reason,
        expectedVersion,
      });
      return r.ok ? { ok: true, value: { kind: "status", status: r.value.status } } : r;
    }
    case "replay": {
      const r = await replayDeadLettersAction({ eventIds: action.eventIds, reason });
      return r.ok ? { ok: true, value: { kind: "replay", result: r.value } } : r;
    }
  }
}

/** Maps one pending engine action onto the shared ConfirmDialog; stays open on any failure. */
export function EngineActionDialog({
  action,
  status,
  onClose,
  onDone,
}: Readonly<{
  action: EngineAction | null;
  status: Schemas["EngineStatusOut"];
  onClose: () => void;
  onDone: (result: EngineActionResult) => void;
}>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (action === null) return null;
  const copy = copyFor(action, status);

  const close = () => {
    setError(null);
    onClose();
  };

  return (
    <ConfirmDialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) close();
      }}
      title={copy.title}
      body={copy.body}
      confirmLabel={copy.confirmLabel}
      tone="warn"
      expectedVersion={status.config_version}
      pending={pending}
      error={error}
      onConfirm={async ({ reason }) => {
        setPending(true);
        setError(null);
        const r = await run(action, reason, status.config_version);
        setPending(false);
        if (!r.ok) {
          setError(r.error.status === 409 ? CONFLICT_MESSAGE : r.error.message);
          return;
        }
        onDone(r.value);
        close();
      }}
    />
  );
}
