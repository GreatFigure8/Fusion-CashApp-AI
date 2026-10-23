/** Client-safe formatting for the reports screens. Report days are UTC. */

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** "2026-10-22" -> "22 Oct 2026". An unparseable value comes back unchanged. */
export function formatReportDate(iso: string): string {
  const m = ISO_DAY.exec(iso);
  if (!m) return iso;
  const month = MONTHS[Number(m[2]) - 1];
  if (month === undefined) return iso;
  return `${Number(m[3])} ${month} ${m[1]}`;
}

export function toIsoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** Yesterday's UTC day as "YYYY-MM-DD". */
export function yesterdayUtc(now: Date): string {
  return toIsoDay(new Date(now.getTime() - 24 * 60 * 60 * 1000));
}

/** Today's UTC day as "YYYY-MM-DD". */
export function todayUtc(now: Date): string {
  return toIsoDay(now);
}

export type LastGenerated = Readonly<{
  at: string;
  by: string;
  by_kind: "user" | "cutover";
}>;

/** "Last generated 07:02 by first event after 07:00 cutover." (times in UTC). */
export function lastGeneratedLabel(last: LastGenerated | null, cutover: string): string {
  if (last === null) return "Not generated yet.";
  const at = new Date(last.at);
  const hh = String(at.getUTCHours()).padStart(2, "0");
  const mm = String(at.getUTCMinutes()).padStart(2, "0");
  const by = last.by_kind === "cutover" ? `first event after ${cutover} cutover` : last.by;
  return `Last generated ${hh}:${mm} by ${by}.`;
}
