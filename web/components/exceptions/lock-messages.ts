import type { ApiError } from "@/lib/api/errors";

export { formatLockTime } from "@/lib/lock-time";

export const LOCK_EXPIRED_TEXT = "Your lock expired — automation may act. Dequeue again";

function ownerOf(err: ApiError): string {
  const owner = err.details[0]?.["owner_name"];
  return typeof owner === "string" && owner !== "" ? owner : "Someone";
}

/** The toast for a lock failure, or null when the error is not a lock error (show the alert). */
export function lockErrorToast(err: ApiError): string | null {
  switch (err.code) {
    case "lock_conflict":
      return `${ownerOf(err)} dequeued this item a moment ago.`;
    case "item_busy":
      return "The line is processing this item; try again in a moment.";
    case "lock_not_held":
      return LOCK_EXPIRED_TEXT;
    default:
      return null;
  }
}
