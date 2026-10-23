"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useState, useTransition } from "react";

import { replayAgainAction } from "@/app/(shell)/lab/actions";
import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";
import { labHref } from "@/lib/lab/view";
import { WINDOW_DAYS_DEFAULT } from "@/lib/lab/schemas";

/** Starts a new replay of the candidate and follows it. */
export function ReplayAgainButton({
  candidateId,
  label = "Replay again",
  variant = "outline",
}: {
  candidateId: string;
  label?: string;
  variant?: "outline" | "default";
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <Button
        variant={variant}
        disabled={pending}
        onClick={() =>
          start(async () => {
            setError(null);
            const result = await replayAgainAction({ candidateId, windowDays: WINDOW_DAYS_DEFAULT });
            if (!result.ok) {
              setError(result.error.message);
              return;
            }
            const href = labHref(candidateId, result.value.id);
            if (href) router.replace(href as Route);
          })
        }
      >
        {pending ? "Starting…" : label}
      </Button>
      {error ? (
        <span role="alert" className="text-[13px] text-err-ink">
          {error}
        </span>
      ) : null}
    </>
  );
}

export function LabEmptyState() {
  return (
    <StateCard
      kind="empty"
      headline="No candidate yet"
      body="Ask the assistant for a change, or pick a matching key to try."
    />
  );
}

export function LabUnreplayedState({ candidateId }: { candidateId: string }) {
  return (
    <StateCard
      kind="empty"
      label="Empty · no replay"
      headline="This candidate hasn't been replayed"
      body="Replay it over the last 30 days to see what would change."
      actions={<ReplayAgainButton candidateId={candidateId} label="Replay" variant="default" />}
    />
  );
}

export function LabStaleState({
  candidateId,
  liveVersion,
}: {
  candidateId: string;
  liveVersion: number;
}) {
  return (
    <StateCard
      kind="error"
      label="Error · stale replay"
      headline={`Live config moved to v${liveVersion}`}
      body="Promote is blocked until you replay against the new version."
      actions={<ReplayAgainButton candidateId={candidateId} />}
    />
  );
}

export function LabReplayFailed({ candidateId }: { candidateId: string }) {
  return (
    <StateCard
      kind="error"
      label="Error · replay"
      headline="The replay didn't finish. Nothing changed."
      actions={<ReplayAgainButton candidateId={candidateId} />}
    />
  );
}

export function LabNoPermissionNote() {
  return (
    <StateCard
      kind="denied"
      label="No permission"
      headline="Replay only"
      body="Operators can replay and read results. Promote needs config write."
      className="min-h-0"
    />
  );
}
