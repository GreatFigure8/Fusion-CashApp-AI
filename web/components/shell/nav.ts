import { hasPermission, type Me } from "@/lib/permissions";

export type NavCountSource = "flow.in_flight" | "exceptions.open" | "review.queue" | "lab.candidates";

export type NavItem = {
  readonly href: string;
  readonly label: string;
  /** Two-letter code shown in the rail chip. */
  readonly code: string;
  readonly permission: string;
  readonly countSource?: NavCountSource;
};

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Dashboard", code: "DB", permission: "reports:read" },
  {
    href: "/flow",
    label: "Flow",
    code: "FL",
    permission: "items:read",
    countSource: "flow.in_flight",
  },
  {
    href: "/exceptions",
    label: "Exceptions",
    code: "EX",
    permission: "items:read",
    countSource: "exceptions.open",
  },
  { href: "/engine", label: "Engine", code: "EN", permission: "reports:read" },
  {
    href: "/review",
    label: "Review",
    code: "RV",
    permission: "items:work",
    countSource: "review.queue",
  },
  { href: "/reports", label: "Reports", code: "RP", permission: "reports:read" },
  {
    href: "/lab",
    label: "Lab",
    code: "LB",
    permission: "lab:run",
    countSource: "lab.candidates",
  },
  { href: "/config", label: "Config", code: "CF", permission: "config:read" },
];

/** The nav items this user may use. Hiding is a convenience; the API enforces the permission. */
export function visibleNav(me: Me): NavItem[] {
  return NAV_ITEMS.filter((item) => hasPermission(me, item.permission));
}
