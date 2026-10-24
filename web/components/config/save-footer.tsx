"use client";

import { useState } from "react";

import { DiffBlock, type DiffLine } from "@/components/common/diff-block";
import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";
import { ActionButton } from "@/components/common/action-button";

import { useStaging } from "./config-staging-provider";
import { ReviewDialog } from "./review-dialog";
import { stagedCount, stagedDiff } from "./staging";
import { formatConfigValue } from "./value-format";

const NEEDS_WRITE = "needs config write";

/** Footer of a group card: diff summary, Revert and Save as vN+1; conflict and invalid states. */
export function SaveFooter({ nextVersion }: { nextVersion: number }) {
  const { state, dispatch, canEdit } = useStaging();
  const [reviewing, setReviewing] = useState(false);
  const count = stagedCount(state);

  if (!canEdit) {
    return (
      <div
        role="region"
        aria-label="Unsaved changes"
        className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-3"
      >
        <span className="font-mono text-xs text-faint">{NEEDS_WRITE}</span>
        <div className="flex gap-2">
          <Button type="button" variant="outline" disabled>
            Revert
          </Button>
          <ActionButton type="button" disabled>
            Save as v{nextVersion}
          </ActionButton>
        </div>
      </div>
    );
  }

  const conflicts = [...state.conflicts];
  const invalid = Object.entries(state.errors).find(([, errs]) => errs.length > 0);
  if (count === 0 && conflicts.length === 0 && !reviewing) return null;

  const lines: DiffLine[] = stagedDiff(state).flatMap((d) => [
    { op: "-" as const, text: `${d.key} ${formatConfigValue(d.editor, d.oldValue, d.unit)}` },
    { op: "+" as const, text: `${d.key} ${formatConfigValue(d.editor, d.newValue, d.unit)}` },
  ]);

  return (
    <>
      <div
        role="region"
        aria-label="Unsaved changes"
        className="space-y-3 border-t border-line px-4 py-3"
      >
        {conflicts.length > 0 ? (
          <StateCard
            kind="error"
            label="Error · conflict"
            headline="Someone saved a newer version first"
            body="Your edit is kept. Review their change, then save again."
            actions={
              <Button type="button" variant="outline" onClick={() => setReviewing(true)}>
                Review the difference
              </Button>
            }
          />
        ) : null}
        {invalid ? (
          <StateCard
            kind="error"
            label="Error · invalid value"
            headline={`${invalid[0]} has an invalid value`}
            body={`${invalid[1][0]?.message ?? "The value was rejected."} Nothing was saved.`}
          />
        ) : null}
        {count > 0 ? <DiffBlock lines={lines} /> : null}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm">
            {count} unsaved {count === 1 ? "change" : "changes"}
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={() => dispatch({ type: "discard" })}>
              Revert
            </Button>
            <ActionButton type="button" glow disabled={count === 0} onClick={() => setReviewing(true)}>
              Save as v{nextVersion}
            </ActionButton>
          </div>
        </div>
      </div>
      <ReviewDialog open={reviewing} onOpenChange={setReviewing} nextVersion={nextVersion} />
    </>
  );
}
