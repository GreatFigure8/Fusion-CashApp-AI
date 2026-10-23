"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

import { useStaging } from "./config-staging-provider";
import { ReviewDialog } from "./review-dialog";
import { stagedCount } from "./staging";

/** Sticky bar: unsaved-change count with Discard and Review & save, or the read-only notice. */
export function SaveFooter() {
  const { state, dispatch, canEdit } = useStaging();
  const [reviewing, setReviewing] = useState(false);
  const count = stagedCount(state);

  if (!canEdit) {
    return (
      <div
        role="region"
        aria-label="Unsaved changes"
        className="sticky bottom-0 mt-4 rounded-xl border bg-card px-4 py-3 text-sm text-muted-foreground"
      >
        Admin role required to edit
      </div>
    );
  }
  if (count === 0 && !reviewing) return null;

  return (
    <>
      <div
        role="region"
        aria-label="Unsaved changes"
        className="sticky bottom-0 mt-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-card px-4 py-3 shadow-md"
      >
        <p className="text-sm">
          {count} unsaved {count === 1 ? "change" : "changes"}
        </p>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={() => dispatch({ type: "discard" })}>
            Discard
          </Button>
          <Button type="button" onClick={() => setReviewing(true)}>
            Review &amp; save
          </Button>
        </div>
      </div>
      <ReviewDialog open={reviewing} onOpenChange={setReviewing} />
    </>
  );
}
