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
      return `Locked by you since ${time}. Automation won't touch this item until you requeue or release it.`;
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
        "flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-sm",
        locked
          ? "border-status-locked/50 bg-status-locked/5"
          : "border-status-attention/50 bg-status-attention/5",
      )}
    >
      <Lock
        aria-hidden
        className={cn("size-4 shrink-0", locked ? "text-status-locked" : "text-status-attention")}
      />
      <span className="min-w-0 flex-1" suppressHydrationWarning>
        {message(props)}
      </span>
      {props.actions ? <div className="flex items-center gap-2">{props.actions}</div> : null}
    </div>
  );
}
