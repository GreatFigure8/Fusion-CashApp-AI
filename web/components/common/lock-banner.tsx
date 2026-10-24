import { Lock } from "lucide-react";
import type * as React from "react";

import { formatLockTime } from "@/lib/lock-time";
import { cn } from "@/lib/utils";

export type LockBannerProps = Readonly<{
  variant: "mine" | "other" | "expired" | "taken_over";
  ownerName?: string;
  /** ISO timestamp, rendered as HH:MM local time. */
  since?: string;
  actions?: React.ReactNode;
}>;

function message({ variant, ownerName, since }: LockBannerProps): string {
  const time = since ? formatLockTime(since) : "";
  switch (variant) {
    case "mine":
      return `Locked by you since ${time}. Automation won't act on this item.`;
    case "other":
      return `Locked by ${ownerName ?? "someone"} since ${time}`;
    case "expired":
      return "Your lock expired — automation may act. Dequeue again";
    case "taken_over":
      return `${ownerName ?? "Someone"} took over this item`;
  }
}

export function LockBanner(props: LockBannerProps): React.JSX.Element {
  const locked = props.variant === "mine" || props.variant === "other";
  return (
    <div
      role="status"
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-xl border px-3 py-2 text-[13px]",
        locked
          ? "border-locked/30 bg-locked-soft text-locked-ink"
          : "border-warn/30 bg-warn-soft text-warn-ink",
      )}
    >
      <Lock
        aria-hidden
        className="size-4 shrink-0"
      />
      <span className="min-w-0 flex-1" suppressHydrationWarning>
        {message(props)}
      </span>
      {props.actions ? <div className="flex items-center gap-2">{props.actions}</div> : null}
    </div>
  );
}
