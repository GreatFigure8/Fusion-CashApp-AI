"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { discardAction, promoteAction } from "@/app/(shell)/lab/actions";
import { ActionButton } from "@/components/common/action-button";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { DiffBlock } from "@/components/common/diff-block";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { Pill } from "@/components/common/pill";
import { Input } from "@/components/ui/input";
import type { Me } from "@/lib/permissions";
import {
  auditCaption,
  canPromote,
  diffLines,
  type LabCandidate,
  type LabReplay,
} from "@/lib/lab/view";

const STALE_STATUS = 409;

/** Promote to live: a required reason, a confirmation, then the audited config write. */
export function PromotePanel({
  me,
  candidate,
  replay,
}: {
  me: Me;
  candidate: LabCandidate;
  replay: LabReplay;
}) {
  const router = useRouter();
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const allowed = canPromote(me, candidate, replay);
  const writer = me.permissions.includes("config:write");
  const trimmed = reason.trim();

  const promote = (confirmed: string) =>
    start(async () => {
      setError(null);
      const result = await promoteAction({
        candidateId: candidate.id,
        replayId: replay.id,
        reason: confirmed,
        expectedVersion: candidate.live_version,
      });
      if (result.ok) {
        setOpen(false);
        return;
      }
      setError(result.error.message);
      // A 409 means live config moved: re-read so the stale state replaces this panel.
      if (result.error.status === STALE_STATUS) {
        setOpen(false);
        router.refresh();
      }
    });

  const discard = () =>
    start(async () => {
      setError(null);
      const result = await discardAction({ candidateId: candidate.id });
      if (!result.ok) setError(result.error.message);
    });

  return (
    <GlassPanel aria-label="Promote to live" tone="accent">
      <PanelHeader title="Promote to live">
        <Pill tone="locked">Audited</Pill>
      </PanelHeader>
      <PanelBody className="grid gap-3">
        <div className="flex flex-wrap gap-2">
          <Pill tone={replay.base_version === candidate.live_version ? "ok" : "warn"} dot>
            Replay ran on current v{replay.base_version}
          </Pill>
          {writer ? (
            <Pill tone="ok" dot>
              You can write config
            </Pill>
          ) : (
            <Pill tone="muted">Replay only</Pill>
          )}
        </div>
        <label className="grid gap-1.5 text-[13px] font-medium">
          <span className="font-mono text-label uppercase tracking-[0.08em] text-muted-foreground">
            Reason · required
          </span>
          <Input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={500}
            disabled={!writer || pending}
            placeholder="Why this change should go live"
          />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            glow
            disabled={!allowed || trimmed === "" || pending}
            onClick={() => setOpen(true)}
          >
            Promote {candidate.id}
          </ActionButton>
          <ActionButton variant="outline" disabled={!writer || pending} onClick={discard}>
            Discard
          </ActionButton>
        </div>
        <p className="font-mono text-label text-muted-foreground">
          {auditCaption(me.display_name, replay.id, candidate.live_version)}
        </p>
        {error ? (
          <p role="alert" className="text-[13px] text-err-ink">
            {error}
          </p>
        ) : null}
      </PanelBody>
      <ConfirmDialog
        key={reason}
        open={open}
        onOpenChange={setOpen}
        title={`Promote ${candidate.id} to live?`}
        body={<DiffBlock lines={diffLines(candidate.config_diff)} caption="Config changes" />}
        confirmLabel={`Promote ${candidate.id}`}
        tone="accent"
        expectedVersion={candidate.live_version}
        defaultReason={trimmed}
        pending={pending}
        error={open ? error : null}
        onConfirm={({ reason: confirmed }) => promote(confirmed)}
      />
    </GlassPanel>
  );
}
