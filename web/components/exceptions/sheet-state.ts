import type { Schemas } from "@/lib/api/types";

export type Stage = Schemas["Stage"];
export type ItemState = Schemas["ItemState"];
export type ItemChangedEvent = Schemas["ItemChangedOut"];
export type LockInfo = Schemas["LockInfoOut"];

export type SheetLockView =
  | { kind: "none" }
  | { kind: "mine"; since: string; expiresAt: string }
  | { kind: "other"; ownerName: string; since: string }
  | { kind: "expired" }
  | { kind: "taken_over"; ownerName: string };

export type SheetNotice =
  | { kind: "moved_on"; stage: Stage; state: ItemState }
  | { kind: "reasons_updated" }
  | null;

export type SheetState = {
  stage: Stage;
  state: ItemState;
  lock: SheetLockView;
  notice: SheetNotice;
  editable: boolean;
};

const MOVED_ON_STATES: readonly ItemState[] = ["PENDING", "IN_PROGRESS", "DONE"];

export function lockView(lock: LockInfo | null, me: string): SheetLockView {
  if (!lock) return { kind: "none" };
  if (lock.owner === me) {
    return { kind: "mine", since: lock.acquired_at, expiresAt: lock.expires_at };
  }
  return { kind: "other", ownerName: lock.owner_name, since: lock.acquired_at };
}

function withLock(
  ev: ItemChangedEvent,
  lock: SheetLockView,
  notice: SheetNotice,
): SheetState {
  return { stage: ev.stage, state: ev.state, lock, notice, editable: lock.kind === "mine" };
}

export function initialSheetState(
  item: { stage: Stage; state: ItemState },
  lock: LockInfo | null,
  me: string,
): SheetState {
  const view = lockView(lock, me);
  return {
    stage: item.stage,
    state: item.state,
    lock: view,
    notice: null,
    editable: view.kind === "mine",
  };
}

/** Folds one `item_changed` event into the open sheet (AC8 b to e; a is `lockExpiredState`). */
export function nextSheetState(
  prev: SheetState,
  ev: ItemChangedEvent,
  me: string,
): SheetState {
  const changed = ev.state !== prev.state || ev.stage !== prev.stage;

  // (b) someone else took my lock
  if (prev.lock.kind === "mine" && ev.lock && ev.lock.owner !== me) {
    return withLock(ev, { kind: "taken_over", ownerName: ev.lock.owner_name }, null);
  }

  // (e) after my own reversal the item is back at receipt matching and I still hold the lock
  if (ev.state === "ESCALATED" && ev.stage === "MATCH_RECEIPT" && ev.lock?.owner === me) {
    return withLock(ev, lockView(ev.lock, me), prev.notice);
  }

  // (c) the pipeline moved the item on without a lock
  if (
    (prev.lock.kind === "mine" || prev.lock.kind === "expired" || prev.lock.kind === "none") &&
    ev.lock === null &&
    changed &&
    MOVED_ON_STATES.includes(ev.state)
  ) {
    return withLock(
      ev,
      { kind: "none" },
      { kind: "moved_on", stage: ev.stage, state: ev.state },
    );
  }

  // (d) re-escalated or parked again
  if ((ev.state === "ESCALATED" || ev.state === "AWAITING_RECEIPT") && changed) {
    return withLock(ev, lockView(ev.lock, me), { kind: "reasons_updated" });
  }

  return withLock(ev, lockView(ev.lock, me), prev.notice);
}

/** (a) Expiry sends no event: the lease timer or a `lock_not_held` renew calls this. */
export function lockExpiredState(prev: SheetState): SheetState {
  return { ...prev, lock: { kind: "expired" }, editable: false };
}
