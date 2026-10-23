import type { Me } from "@/lib/permissions";

const ROLE_ORDER = ["ADMIN", "OPERATOR", "REVERSER", "VIEWER"] as const;

/** The most powerful role the user holds, lower-cased for display; null when none is mapped. */
export function highestRole(me: Me): string | null {
  const held = me.roles as readonly string[];
  const top = ROLE_ORDER.find((role) => held.includes(role));
  return top ? top.toLowerCase() : null;
}

/** `d MMM yyyy HH:mm` in UTC, for audit lines. */
export function formatUtcStamp(date: Date): string {
  const text = new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
  return text.replace(",", "");
}

/** Up to two initials from a display name, for avatars. */
export function initials(name: string): string {
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase());
  return letters.join("") || "?";
}
