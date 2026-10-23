import { formatDistanceStrict } from "date-fns";

/** Client-safe formatting. Money stays a decimal string: no float ever touches an amount. */

const AMOUNT = /^(-?)(\d+)(?:\.(\d+))?$/;
const WORK_ITEM = /^(?:WI-)?(\d{1,15})$/i;
const EM_DASH = "—";

function groupDigits(integer: string, currency: string | null | undefined): string {
  if (integer.length <= 3) return integer;
  if (currency === "INR") {
    // Indian lakh grouping: the last three digits, then pairs (1,92,400).
    const head = integer.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
    return `${head},${integer.slice(-3)}`;
  }
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** `"12480.00","USD"` gives `12,480.00 USD`. Null or empty gives an em dash. Never emits `$`. */
export function formatMoney(
  amount: string | null | undefined,
  currency: string | null | undefined,
): string {
  if (amount === null || amount === undefined || amount.trim() === "") return EM_DASH;
  const match = AMOUNT.exec(amount.trim());
  const suffix = currency ? ` ${currency}` : "";
  if (!match) return `${amount}${suffix}`;
  const [, sign = "", integer = "0", fraction = ""] = match;
  const cents = fraction.padEnd(2, "0").slice(0, 2);
  const negative = sign === "-" && /[1-9]/.test(`${integer}${cents}`);
  return `${negative ? "-" : ""}${groupDigits(integer, currency)}.${cents}${suffix}`;
}

export function formatWorkItemId(id: number): string {
  return `WI-${id}`;
}

/** Accepts `20481` or `WI-20481` (any case); anything else gives null. */
export function parseWorkItemId(value: string): number | null {
  const match = WORK_ITEM.exec(value.trim());
  if (!match?.[1]) return null;
  const id = Number(match[1]);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

/** `AWAITING_RECEIPT` and `payment-success` give `Awaiting receipt` and `Payment success`. */
export function humanizeEnum(value: string): string {
  const words = value.replace(/[_-]+/g, " ").trim().toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** `42s`, `3m 10s`, `2h 5m`, `1d 3h`; null gives an em dash. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return EM_DASH;
  }
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  if (total < 3_600) return `${Math.floor(total / 60)}m ${total % 60}s`;
  if (total < 86_400) return `${Math.floor(total / 3_600)}h ${Math.floor((total % 3_600) / 60)}m`;
  return `${Math.floor(total / 86_400)}d ${Math.floor((total % 86_400) / 3_600)}h`;
}

/** `2 minutes ago`. `now` is injectable so renders and tests are deterministic. */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return EM_DASH;
  return formatDistanceStrict(then, now, { addSuffix: true });
}

/** Whole minutes between an ISO time and now, never negative; null when the time is unknown. */
export function minutesSince(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  return Math.max(0, Math.floor((now.getTime() - then) / 60_000));
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return EM_DASH;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}
