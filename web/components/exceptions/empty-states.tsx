import type { Route } from "next";
import { CheckCircle2, SearchX } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/common/empty-state";

export function NoExceptions(): React.JSX.Element {
  return (
    <EmptyState
      icon={CheckCircle2}
      title="No exceptions"
      description="Everything that arrived has been applied or is still moving."
      action={
        <Link href={"/flow" as Route} className="text-sm underline underline-offset-4">
          See the flow
        </Link>
      }
    />
  );
}

export function NoMatches({ clearHref }: Readonly<{ clearHref: string }>): React.JSX.Element {
  return (
    <EmptyState
      icon={SearchX}
      title="No exceptions match these filters"
      action={
        <Link href={clearHref as Route} className="text-sm underline underline-offset-4">
          Clear filters
        </Link>
      }
    />
  );
}
