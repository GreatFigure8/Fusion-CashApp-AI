"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { toast } from "sonner";

import { dequeueAction, releaseLockAction } from "@/app/(shell)/exceptions/_lib/actions";
import { LockBanner } from "@/components/common/lock-banner";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";

import type { RemittanceExtraction } from "./edit-model";
import { lockErrorToast } from "./lock-messages";
import { RequeueDialog } from "./requeue-dialog";
import { useSheet } from "./sheet-context";

/** Shared lock handlers: dequeue and unlock, with the same toasts and refresh. */
function useLockHandlers() {
  const sheet = useSheet();
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  const fail = (error: ApiError) => {
    if (error.code === "lock_not_held") sheet.lockExpired();
    toast.error(lockErrorToast(error) ?? error.message);
  };

  const dequeue = () =>
    startTransition(async () => {
      const result = await dequeueAction({ itemId: sheet.itemId });
      if (!result.ok) return fail(result.error);
      sheet.lockAcquired(result.value);
      router.refresh();
    });

  const release = () =>
    startTransition(async () => {
      const result = await releaseLockAction({ itemId: sheet.itemId });
      if (!result.ok) return fail(result.error);
      sheet.lockReleased();
      router.refresh();
    });

  return { sheet, pending, dequeue, release };
}

/** The lock banner, or the Dequeue button when nobody holds the item. */
export function LockStatus(): React.JSX.Element | null {
  const { sheet, pending, dequeue } = useLockHandlers();
  const { lock } = sheet.sheet;

  const dequeueButton = sheet.canWork ? (
    <Button size="sm" onClick={dequeue} disabled={pending}>
      Dequeue
    </Button>
  ) : null;

  switch (lock.kind) {
    case "none":
      return dequeueButton;
    case "mine":
      return <LockBanner variant="mine" since={lock.since} />;
    case "other":
      return <LockBanner variant="other" ownerName={lock.ownerName} since={lock.since} />;
    case "expired":
      return <LockBanner variant="expired" actions={dequeueButton} />;
    case "taken_over":
      return <LockBanner variant="taken_over" ownerName={lock.ownerName} />;
  }
}

/** Requeue and Unlock, shown only while I hold the lock. */
export function LockActions({
  final,
  errorCode = null,
}: Readonly<{
  final: RemittanceExtraction | null;
  errorCode?: Schemas["ErrorCode"] | null;
}>): React.JSX.Element | null {
  const { sheet, pending, release } = useLockHandlers();
  if (sheet.sheet.lock.kind !== "mine") return null;
  return (
    <>
      <RequeueDialog final={final} errorCode={errorCode} />
      <Button size="sm" variant="outline" onClick={release} disabled={pending}>
        Unlock
      </Button>
    </>
  );
}
