const HH_MM = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** "10:42" in the viewer's local time. Client-safe and pure. */
export function formatLockTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : HH_MM.format(date);
}
