"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";

import { reverseAction } from "@/app/(shell)/exceptions/_lib/actions";
import { ErrorAlert } from "@/components/common/error-alert";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ApiError } from "@/lib/api/errors";

import { isReverseConfirmValid } from "./edit-model";
import { lockErrorToast } from "./lock-messages";
import { useSheet } from "./sheet-context";

type Props = Readonly<{ ledgerId: number; receiptNumber: string }>;

export function ReverseDialog({ ledgerId, receiptNumber }: Props): React.JSX.Element {
  const sheet = useSheet();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [pending, startTransition] = useTransition();

  const valid = isReverseConfirmValid({ reason, typed, receiptNumber });

  const confirm = () =>
    startTransition(async () => {
      const result = await reverseAction({
        itemId: sheet.itemId,
        ledgerId,
        reason: reason.trim(),
        confirmReceiptNumber: typed.trim(),
      });
      if (!result.ok) {
        const text = lockErrorToast(result.error);
        if (result.error.code === "lock_not_held") sheet.lockExpired();
        if (text) toast.error(text);
        setError(result.error);
        return;
      }
      toast.success("Application reversed");
      setOpen(false);
      setReason("");
      setTyped("");
      setError(null);
      router.refresh();
    });

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger render={<Button size="xs" variant="destructive" />}>
        Reverse…
      </AlertDialogTrigger>
      <AlertDialogContent className="sm:max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>Reverse this application?</AlertDialogTitle>
          <AlertDialogDescription>
            This removes the application from receipt {receiptNumber} in Fusion and sends the item
            back to receipt matching. Type the receipt number to confirm.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor={`reverse-reason-${ledgerId}`}>Reason (required)</Label>
            <Textarea
              id={`reverse-reason-${ledgerId}`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              maxLength={1000}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`reverse-confirm-${ledgerId}`}>
              Receipt number <span className="font-mono">{receiptNumber}</span>
            </Label>
            <Input
              id={`reverse-confirm-${ledgerId}`}
              className="font-mono"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoComplete="off"
            />
          </div>
          {error ? <ErrorAlert error={error} title="Couldn't reverse the application" /> : null}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button variant="destructive" disabled={!valid || pending} onClick={confirm}>
            {pending ? "Reversing…" : "Reverse application"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
