"use client";

import type { Route } from "next";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";

import { requeueAction } from "@/app/(shell)/exceptions/_lib/actions";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Schemas } from "@/lib/api/types";
import { formatWorkItemId } from "@/lib/format";

import {
  buildRequeueBody,
  diffSummary,
  EMPTY_FORM_VALUES,
  type RemittanceExtraction,
} from "./edit-model";
import { lockErrorToast } from "./lock-messages";
import { useSheet } from "./sheet-context";

type Props = Readonly<{
  final: RemittanceExtraction | null;
  errorCode?: Schemas["ErrorCode"] | null;
}>;

export function RequeueDialog({ final, errorCode = null }: Props): React.JSX.Element {
  const sheet = useSheet();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [pending, startTransition] = useTransition();

  const { draft } = sheet;
  const toReceipt = draft.receipt !== undefined || errorCode === "RECEIPT_AMBIGUOUS";
  const summary = diffSummary(draft.before ?? EMPTY_FORM_VALUES, draft.after ?? EMPTY_FORM_VALUES, {
    receipt: draft.receipt?.number,
    customer: draft.customer,
  });

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) setNote(summary.count > 0 ? summary.text : "");
  };

  const confirm = () =>
    startTransition(async () => {
      const body = buildRequeueBody({
        final,
        before: draft.before,
        after: draft.after,
        receiptId: draft.receipt?.id,
        customerNumber: draft.customer,
        note,
      });
      const result = await requeueAction({ itemId: sheet.itemId, body });
      if (!result.ok) {
        setOpen(false);
        sheet.setRequeueError(result.error);
        const toastText = lockErrorToast(result.error);
        if (result.error.code === "lock_not_held") sheet.lockExpired();
        if (toastText) toast.error(toastText);
        return;
      }
      sheet.setRequeueError(null);
      toast.success(`Requeued ${formatWorkItemId(sheet.itemId)}`);
      setOpen(false);
      const params = new URLSearchParams(searchParams.toString());
      params.delete("item");
      const query = params.toString();
      router.replace((query ? `${pathname}?${query}` : pathname) as Route);
      router.refresh();
    });

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogTrigger
        render={<Button size="sm" className="shadow-[0_0_18px_-4px_var(--acc-hi)]" />}
      >
        {toReceipt ? "Requeue to match receipt" : "Requeue"}
      </AlertDialogTrigger>
      <AlertDialogContent className="sm:max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>Requeue {formatWorkItemId(sheet.itemId)}</AlertDialogTitle>
          <AlertDialogDescription>{summary.text}</AlertDialogDescription>
        </AlertDialogHeader>
        <div className="grid gap-1.5">
          <Label htmlFor="requeue-note">Note (required)</Label>
          <Textarea
            id="requeue-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={4}
            maxLength={2000}
          />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button onClick={confirm} disabled={pending || note.trim() === ""}>
            {pending ? "Requeuing…" : "Requeue"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
