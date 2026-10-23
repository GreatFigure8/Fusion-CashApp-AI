import { ShieldAlertIcon } from "lucide-react";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { hasPermission, type Me } from "@/lib/permissions";

export function ForbiddenState({ role }: { role: string }) {
  return (
    <EmptyState
      icon={ShieldAlertIcon}
      title="You don't have access to this page."
      description={`Ask an administrator for the ${role} role.`}
    />
  );
}

/** Hides what the user can't use. The API still enforces every permission. */
export function RequirePermission({
  me,
  permission,
  role,
  children,
}: {
  me: Me;
  permission: string;
  role: string;
  children: ReactNode;
}) {
  if (!hasPermission(me, permission)) return <ForbiddenState role={role} />;
  return <>{children}</>;
}
