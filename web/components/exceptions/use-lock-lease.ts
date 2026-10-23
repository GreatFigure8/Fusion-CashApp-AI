"use client";

import { useEffect, useEffectEvent } from "react";

import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import type { Result } from "@/lib/result";

export const MIN_LEASE_MS = 30_000;

type UseLockLeaseOptions = {
  /** True while the sheet is open and I hold the lock. */
  active: boolean;
  expiresAt: string | null;
  /** `expires_at - acquired_at` from the acquire response; null when unknown (deep link). */
  leaseMs: number | null;
  renew: () => Promise<Result<Schemas["LockInfoOut"], ApiError>>;
  onRenewed: (info: Schemas["LockInfoOut"]) => void;
  onExpired: () => void;
};

/** Renews my lock every lease/3 and detects expiry by timer (lazy expiry sends no event). */
export function useLockLease(options: UseLockLeaseOptions): void {
  const { active, expiresAt, leaseMs } = options;
  const renew = useEffectEvent(() => options.renew());
  const onRenewed = useEffectEvent((info: Schemas["LockInfoOut"]) => options.onRenewed(info));
  const onExpired = useEffectEvent(() => options.onExpired());

  useEffect(() => {
    if (!active || !expiresAt) return;
    const expiry = Date.parse(expiresAt);
    const lease = leaseMs ?? Math.max(expiry - Date.now(), MIN_LEASE_MS);
    const step = lease / 3;
    let cancelled = false;
    let renewTimer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      const result = await renew();
      if (cancelled) return;
      if (result.ok) {
        // A new expiry re-runs this effect, which restarts both timers (the cadence reset).
        onRenewed(result.value);
        return;
      }
      if (result.error.code === "lock_not_held") {
        onExpired();
        return;
      }
      // item_busy and transient failures: try again on the next tick.
      renewTimer = setTimeout(tick, step);
    };

    renewTimer = setTimeout(tick, step);
    const expiryTimer = setTimeout(() => onExpired(), Math.max(expiry - Date.now(), 0));
    return () => {
      cancelled = true;
      clearTimeout(renewTimer);
      clearTimeout(expiryTimer);
    };
  }, [active, expiresAt, leaseMs]);
}
