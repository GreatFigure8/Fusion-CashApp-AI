"use client";

import { LockIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { GlassPanel } from "@/components/common/glass-panel";
import { Money } from "@/components/common/money";
import { StatusBadge } from "@/components/common/status-badge";
import { useFlowStream } from "@/components/shell/flow-stream";
import type { Schemas } from "@/lib/api/types";
import { formatDateTime, formatWorkItemId, humanizeEnum } from "@/lib/format";

const REFRESH_DEBOUNCE_MS = 1_000;

/**
 * The item's identity and status. An `item_changed` event for this item patches the header at
 * once, then pulls fresh history and lines with one debounced `router.refresh()`.
 */
export function ItemHeader({
  item,
  lock,
}: {
  item: Schemas["ItemOut"];
  lock: Schemas["LockInfoOut"] | null;
}) {
  const router = useRouter();
  const { subscribeItemChanged } = useFlowStream();
  const [patch, setPatch] = useState<Schemas["ItemChangedOut"] | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    const unsubscribe = subscribeItemChanged((event) => {
      if (event.id !== item.id) return;
      setPatch(event);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => router.refresh(), REFRESH_DEBOUNCE_MS);
    });
    return () => {
      unsubscribe();
      clearTimeout(timer.current);
    };
  }, [subscribeItemChanged, item.id, router]);

  // Once the refreshed props are as new as the event, the props win again.
  const newer = patch !== null && Date.parse(patch.updated_at) > Date.parse(item.updated_at);
  const stage = newer ? patch.stage : item.stage;
  const state = newer ? patch.state : item.state;
  const paymentStatus = newer ? patch.payment_status : item.payment_status;
  const currentLock = newer ? patch.lock : lock;

  return (
    <GlassPanel as="header" className="flex flex-col gap-1.5 p-3.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="font-mono text-lg font-semibold text-brand-ink">{formatWorkItemId(item.id)}</h1>
        <span className="text-sm text-muted-foreground">{humanizeEnum(stage)}</span>
        <StatusBadge kind="item_state" value={state} />
        {paymentStatus ? <StatusBadge kind="payment_status" value={paymentStatus} /> : null}
        <Money amount={item.amount} currency={item.currency} className="ml-auto text-base" />
      </div>
      <p className="text-sm text-muted-foreground">{item.payer_name ?? "Payer not yet read"}</p>
      {currentLock ? (
        <p data-slot="lock-line" className="flex items-center gap-1.5 text-sm text-locked-ink">
          <LockIcon aria-hidden className="size-4" />
          Locked by {currentLock.owner_name} since {formatDateTime(currentLock.acquired_at)}
        </p>
      ) : null}
    </GlassPanel>
  );
}
