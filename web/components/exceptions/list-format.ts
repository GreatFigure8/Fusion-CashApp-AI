/** Pure text helpers for the exceptions list footer and lock-owner column. */

const nf = new Intl.NumberFormat("en-US");

export function footerText(args: {
  total: number;
  appliedHidden: number | null;
  showApplied: boolean;
}): string {
  const { total, appliedHidden, showApplied } = args;
  if (showApplied) {
    return `${nf.format(total)} ${total === 1 ? "item" : "items"} · applied items shown`;
  }
  const base = `${nf.format(total)} ${total === 1 ? "exception" : "exceptions"}`;
  return appliedHidden === null ? base : `${base} · ${nf.format(appliedHidden)} applied items hidden`;
}

export function lockOwnerLabel(
  lock: Readonly<{ owner: string; owner_name: string }> | null | undefined,
  meSubject: string | null | undefined,
): string | null {
  if (!lock) return null;
  if (meSubject && lock.owner === meSubject) return "You";
  return lock.owner_name.trim() || lock.owner;
}
