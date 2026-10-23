"use client";

import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";

import { useSheet } from "./sheet-context";

/** Shown when someone else holds the lock; "View read-only" dismisses it into the read-only detail. */
export function LockConflictCard({
  dismissed,
  onDismiss,
}: Readonly<{ dismissed: boolean; onDismiss: () => void }>): React.JSX.Element | null {
  const { sheet } = useSheet();
  if (dismissed || sheet.lock.kind !== "other") return null;
  return (
    <StateCard
      kind="error"
      label="Error · lock conflict"
      headline={`${sheet.lock.ownerName} locked this item first`}
      body="You can view it read-only until they release it."
      actions={
        <Button size="sm" variant="outline" onClick={onDismiss}>
          View read-only
        </Button>
      }
    />
  );
}
