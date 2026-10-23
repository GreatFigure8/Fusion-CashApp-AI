"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { ApiError } from "@/lib/api/errors";

import { renewLockAction } from "@/app/(shell)/exceptions/_lib/actions";

import type { EditFormValues } from "./edit-model";
import {
  initialSheetState,
  lockExpiredState,
  nextSheetState,
  type ItemChangedEvent,
  type ItemState,
  type LockInfo,
  type SheetState,
  type Stage,
} from "./sheet-state";
import { useItemLive } from "./use-item-live";
import { useLockLease } from "./use-lock-lease";

export type RequeueDraft = {
  /** The form values as extracted; null when there is no adjudicated extraction to edit. */
  before: EditFormValues | null;
  after: EditFormValues | null;
  receipt?: { id: number; number: string };
  customer?: string;
};

type SheetContextValue = {
  itemId: number;
  me: string;
  canWork: boolean;
  sheet: SheetState;
  draft: RequeueDraft;
  requeueError: ApiError | null;
  setBaseline: (values: EditFormValues | null) => void;
  setAfter: (values: EditFormValues) => void;
  setReceipt: (receipt: RequeueDraft["receipt"]) => void;
  setCustomer: (customer: string | undefined) => void;
  setRequeueError: (error: ApiError | null) => void;
  lockAcquired: (info: LockInfo) => void;
  lockReleased: () => void;
  lockExpired: () => void;
};

const SheetContext = createContext<SheetContextValue | null>(null);

export function useSheet(): SheetContextValue {
  const value = useContext(SheetContext);
  if (!value) throw new Error("useSheet must be used inside <SheetProvider>");
  return value;
}

type ProviderProps = Readonly<{
  itemId: number;
  me: string;
  canWork: boolean;
  item: { stage: Stage; state: ItemState; version: number };
  lock: LockInfo | null;
  children: ReactNode;
}>;

export function SheetProvider({
  itemId,
  me,
  canWork,
  item,
  lock,
  children,
}: ProviderProps): React.JSX.Element {
  const [sheet, setSheet] = useState<SheetState>(() => initialSheetState(item, lock, me));
  const [seenVersion, setSeenVersion] = useState(item.version);
  const [leaseMs, setLeaseMs] = useState<number | null>(null);
  const [draft, setDraft] = useState<RequeueDraft>({ before: null, after: null });
  const [requeueError, setRequeueError] = useState<ApiError | null>(null);

  // A refresh brings authoritative server state: adopt it, keeping any notice already raised.
  if (item.version !== seenVersion) {
    setSeenVersion(item.version);
    setSheet((prev) => ({ ...initialSheetState(item, lock, me), notice: prev.notice }));
  }

  useItemLive(itemId, (event: ItemChangedEvent) =>
    setSheet((prev) => nextSheetState(prev, event, me)),
  );

  const lockExpired = useCallback(() => setSheet((prev) => lockExpiredState(prev)), []);

  const lockAcquired = useCallback(
    (info: LockInfo) => {
      setLeaseMs(Date.parse(info.expires_at) - Date.parse(info.acquired_at));
      setSheet((prev) => ({
        ...prev,
        lock: { kind: "mine", since: info.acquired_at, expiresAt: info.expires_at },
        editable: true,
      }));
    },
    [],
  );

  const lockReleased = useCallback(
    () => setSheet((prev) => ({ ...prev, lock: { kind: "none" }, editable: false })),
    [],
  );

  useLockLease({
    active: sheet.lock.kind === "mine",
    expiresAt: sheet.lock.kind === "mine" ? sheet.lock.expiresAt : null,
    leaseMs,
    renew: () => renewLockAction({ itemId }),
    onRenewed: (info) =>
      setSheet((prev) =>
        prev.lock.kind === "mine"
          ? { ...prev, lock: { ...prev.lock, expiresAt: info.expires_at } }
          : prev,
      ),
    onExpired: lockExpired,
  });

  const value = useMemo<SheetContextValue>(
    () => ({
      itemId,
      me,
      canWork,
      sheet,
      draft,
      requeueError,
      setBaseline: (before) => setDraft((d) => ({ ...d, before, after: before })),
      setAfter: (after) => setDraft((d) => ({ ...d, after })),
      setReceipt: (receipt) => setDraft((d) => ({ ...d, receipt })),
      setCustomer: (customer) => setDraft((d) => ({ ...d, customer })),
      setRequeueError,
      lockAcquired,
      lockReleased,
      lockExpired,
    }),
    [itemId, me, canWork, sheet, draft, requeueError, lockAcquired, lockReleased, lockExpired],
  );

  return <SheetContext.Provider value={value}>{children}</SheetContext.Provider>;
}
