"use client";

import { useEffect, useState } from "react";

import { labOpenCountAction } from "@/app/(shell)/lab/actions";

/** The nav count hook for the `lab.candidates` source: open candidates; null when unreadable. */
export function useLabOpenCount(): number | null {
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    void labOpenCountAction().then((result) => {
      if (live) setCount(result.ok ? result.value : null);
    });
    return () => {
      live = false;
    };
  }, []);
  return count;
}
