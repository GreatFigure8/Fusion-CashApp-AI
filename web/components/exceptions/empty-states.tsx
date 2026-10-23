import type { Route } from "next";
import Link from "next/link";

import { StateCard } from "@/components/common/state-card";

export function NoExceptions(): React.JSX.Element {
  return (
    <StateCard
      kind="empty"
      label="Empty"
      headline="No exceptions right now"
      body="Everything applied or is fixing itself. Applied items stay hidden unless you show them."
    />
  );
}

export function NoMatches({ clearHref }: Readonly<{ clearHref: string }>): React.JSX.Element {
  return (
    <StateCard
      kind="empty"
      headline="No exceptions match these filters"
      actions={
        <Link href={clearHref as Route} className="text-sm underline underline-offset-4">
          Clear filters
        </Link>
      }
    />
  );
}
