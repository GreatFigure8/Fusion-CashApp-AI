import { ActivityIcon, AlertOctagonIcon, FileBarChartIcon, SettingsIcon } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { hasPermission, type Me } from "@/lib/permissions";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  permission: string;
};

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/flow", label: "Flow", icon: ActivityIcon, permission: "items:read" },
  { href: "/exceptions", label: "Exceptions", icon: AlertOctagonIcon, permission: "items:read" },
  { href: "/reports", label: "Reports", icon: FileBarChartIcon, permission: "reports:read" },
  { href: "/config", label: "Config", icon: SettingsIcon, permission: "config:read" },
];

/** The nav items this user may use. Hiding is a convenience; the API enforces the permission. */
export function visibleNav(me: Me): NavItem[] {
  return NAV_ITEMS.filter((item) => hasPermission(me, item.permission));
}
