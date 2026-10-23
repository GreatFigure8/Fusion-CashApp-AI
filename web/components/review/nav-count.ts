"use client";

import { useEffect, useState } from "react";

import { refreshReviewQueue } from "@/app/(shell)/review/actions";

/**
 * The number of items still under review, for the nav badge; null when it cannot be read.
 * Reads the queue's `total` through the same server action the board uses.
 */
export async function reviewOpenCount(): Promise<number | null> {
  const result = await refreshReviewQueue();
  return result.ok ? result.value.total : null;
}

/**
 * The nav count hook for the `review.queue` source (glass-theme-shell's `NavCountHook`).
 * The shell's `NAV_COUNT_SOURCES["review.queue"]` entry points here.
 */
export function useReviewOpenCount(): number | null {
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    void reviewOpenCount().then((value) => {
      if (live) setCount(value);
    });
    return () => {
      live = false;
    };
  }, []);
  return count;
}
