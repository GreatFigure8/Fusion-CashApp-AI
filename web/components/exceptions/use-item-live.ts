"use client";

import { useRouter } from "next/navigation";
import { useEffect, useEffectEvent, useRef } from "react";

import { useFlowStream } from "@/components/shell/flow-stream";

import type { ItemChangedEvent } from "./sheet-state";

const REFRESH_DEBOUNCE_MS = 500;

/**
 * Folds `item_changed` events for the open item into the sheet, then asks the server to re-read
 * the body (why-stuck, auto-fixes, history). Uses the one shared `/flow/stream` subscription.
 */
export function useItemLive(itemId: number, onEvent: (event: ItemChangedEvent) => void): void {
  const { subscribeItemChanged } = useFlowStream();
  const router = useRouter();
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const handle = useEffectEvent((event: ItemChangedEvent) => {
    if (event.id !== itemId) return;
    onEvent(event);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => router.refresh(), REFRESH_DEBOUNCE_MS);
  });

  useEffect(() => {
    const unsubscribe = subscribeItemChanged((event) => handle(event));
    return () => {
      unsubscribe();
      clearTimeout(timer.current);
    };
  }, [subscribeItemChanged]);
}
