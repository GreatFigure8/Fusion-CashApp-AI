import type { LucideIcon } from "lucide-react";
import { InboxIcon } from "lucide-react";
import type { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action,
  icon: Icon = InboxIcon,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  icon?: LucideIcon;
}) {
  return (
    <div
      data-slot="empty-state"
      className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center"
    >
      <Icon aria-hidden className="size-8 text-muted-foreground" />
      <h2 className="text-sm font-medium">{title}</h2>
      {description ? <p className="max-w-prose text-sm text-muted-foreground">{description}</p> : null}
      {action}
    </div>
  );
}
