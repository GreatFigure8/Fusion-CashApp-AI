import Link from "next/link";

import { EmptyState } from "@/components/common/empty-state";
import { Button } from "@/components/ui/button";

export default function ItemNotFound() {
  return (
    <EmptyState
      title="Item not found"
      description="There is no work item with that id, or it was removed."
      action={<Button variant="outline" render={<Link href="/flow" />}>Back to the flow</Button>}
    />
  );
}
