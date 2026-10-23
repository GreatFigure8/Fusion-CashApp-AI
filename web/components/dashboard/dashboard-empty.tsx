import Link from "next/link";

import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";
import { windowDescription } from "@/lib/metrics/format";

export function DashboardEmpty({ window }: { window: string }) {
  return (
    <StateCard
      kind="empty"
      headline="Nothing completed in this window"
      body={`No item reached done in the last ${windowDescription(window)}. Try 30 days or open the Flow monitor.`}
      actions={
        <span className="flex gap-2">
          <Button variant="outline" size="sm" render={<Link href="/dashboard?window=30d" />}>
            Show 30 days
          </Button>
          <Button variant="outline" size="sm" render={<Link href="/flow" />}>
            Open Flow
          </Button>
        </span>
      }
    />
  );
}
