const DASH = "—";

/** A 0..1 rate as a percentage; null (not measured) is a dash, never 0%. */
export function formatPct(rate: number | null | undefined, digits = 1): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return DASH;
  return `${(rate * 100).toFixed(digits)}%`;
}

/** `96.8% · n 212`, or a dash when nothing was measured. */
export function formatAccuracy(accuracy: number | null | undefined, n: number): string {
  if (accuracy === null || accuracy === undefined || n <= 0) return DASH;
  return `${formatPct(accuracy)} · n ${n}`;
}

/** `Oldest 11d of 30d aging`; a dash when nothing is waiting. */
export function formatAge(days: number | null | undefined, limit: number): string {
  if (days === null || days === undefined) return `No receipts waiting · ${limit}d aging`;
  return `Oldest ${days}d of ${limit}d aging`;
}

export function windowLabel(window: string): string {
  return window;
}

export function windowDescription(window: string): string {
  switch (window) {
    case "24h":
      return "24 hours";
    case "7d":
      return "7 days";
    case "30d":
      return "30 days";
    default:
      return window;
  }
}

/** Whole seconds between two instants, never negative. */
export function secondsAgo(at: number, now: number): number {
  return Math.max(0, Math.floor((now - at) / 1000));
}

/** `HH:MM:SS` in UTC. */
export function formatClock(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return DASH;
  return date.toISOString().slice(11, 19);
}

/** `HH:MM` in UTC. */
export function formatClockShort(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return DASH;
  return date.toISOString().slice(11, 16);
}
