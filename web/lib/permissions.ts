import type { Schemas } from "@/lib/api/types";

/** Client-safe: the UI only hides what a user can't do. The API is the control. */
export type Me = Schemas["MeResponse"];

export function hasPermission(me: Me, permission: string): boolean {
  return (me.permissions as readonly string[]).includes(permission);
}

/** The permission each shell route needs, and the role named in the "ask an administrator" state. */
export const ROUTE_PERMISSIONS = {
  "/dashboard": { permission: "reports:read", role: "VIEWER" },
  "/flow": { permission: "items:read", role: "VIEWER" },
  "/exceptions": { permission: "items:read", role: "VIEWER" },
  "/reports": { permission: "reports:read", role: "VIEWER" },
  "/config": { permission: "config:read", role: "VIEWER" },
  "/engine": { permission: "reports:read", role: "VIEWER" },
  "/review": { permission: "items:read", role: "VIEWER" },
  "/lab": { permission: "lab:run", role: "OPERATOR" },
} as const;
