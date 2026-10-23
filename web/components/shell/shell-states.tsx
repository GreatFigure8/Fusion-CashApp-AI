"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ActionButton } from "@/components/common/action-button";
import { GlassPanel } from "@/components/common/glass-panel";
import { SkeletonRows } from "@/components/common/skeleton-rows";
import { StateCard } from "@/components/common/state-card";
import { actionButtonVariants } from "@/components/common/action-button";

const RETRY_SECONDS = 8;

/** Skeleton rail, bar and block shown while the session loads. */
export function ShellSkeleton() {
  return (
    <div className="bg-blueprint flex min-h-screen flex-wrap gap-4 p-4" aria-busy="true">
      <GlassPanel as="div" className="min-w-[200px] flex-[1_1_200px] self-start p-3">
        <SkeletonRows rows={4} height={110 / 4} />
      </GlassPanel>
      <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-4">
        <GlassPanel as="div" className="p-3">
          <SkeletonRows rows={1} height={30} />
        </GlassPanel>
        <GlassPanel as="div" className="p-4">
          <SkeletonRows rows={1} height={80} caption="Loading your session…" />
        </GlassPanel>
      </div>
    </div>
  );
}

/** The user signed in but no role is mapped to their identity-domain groups. */
export function DeniedState({ requestAccessUrl }: { requestAccessUrl: string | null }) {
  const href = requestAccessUrl ?? "mailto:?subject=CashApp%20access%20request";
  return (
    <div className="bg-blueprint grid min-h-screen place-items-center p-4">
      <StateCard
        kind="denied"
        label="Empty · no role"
        headline="No role is mapped to your groups"
        body="Your identity-domain groups are not mapped to an app role yet. An admin maps them in Config."
        className="w-full max-w-xl"
        actions={
          <a href={href} className={actionButtonVariants({ variant: "outline" })}>
            Request access
          </a>
        }
      />
    </div>
  );
}

/** The API is unreachable. Counts down, then refreshes; "Retry now" refreshes at once. */
export function ApiDownState() {
  const router = useRouter();
  const [left, setLeft] = useState(RETRY_SECONDS);

  useEffect(() => {
    const timer = setInterval(() => {
      setLeft((value) => value - 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (left > 0) return;
    router.refresh();
    // Restart the countdown after each attempt; a state reset after the refresh call is intended.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLeft(RETRY_SECONDS);
  }, [left, router]);

  return (
    <div className="bg-blueprint grid min-h-screen place-items-center p-4">
      <StateCard
        kind="error"
        label="Error · API unreachable"
        headline="The cash app API is not answering"
        body={`Pipeline workers keep running. Retrying in ${left} seconds.`}
        className="w-full max-w-xl"
        actions={
          <ActionButton
            variant="outline"
            onClick={() => {
              router.refresh();
              setLeft(RETRY_SECONDS);
            }}
          >
            Retry now
          </ActionButton>
        }
      />
    </div>
  );
}
