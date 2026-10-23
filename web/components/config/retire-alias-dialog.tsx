"use client";

import { useState, useTransition } from "react";

import { retireAlias } from "@/app/(shell)/config/actions";
import { ErrorAlert } from "@/components/common/error-alert";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ApiError } from "@/lib/api/errors";

import { reasonSchema } from "./config-schemas";

/** Confirms retiring one alias with a required reason. Errors stay in the dialog. */
export function RetireAliasDialog({
  alias,
  onClose,
}: {
  alias: { id: number; alias_text: string } | null;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [pending, startTransition] = useTransition();

  function close() {
    setReason("");
    setReasonError(null);
    setError(null);
    onClose();
  }

  function submit() {
    if (!alias) return;
    const parsed = reasonSchema.safeParse(reason);
    if (!parsed.success) {
      setReasonError(parsed.error.issues[0]?.message ?? "Enter a reason.");
      return;
    }
    setReasonError(null);
    startTransition(async () => {
      const res = await retireAlias({ aliasId: alias.id, reason: parsed.data });
      if (!res.ok) {
        setError(res.error);
        return;
      }
      close();
    });
  }

  return (
    <AlertDialog open={alias !== null} onOpenChange={(open) => (open ? undefined : close())}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Retire alias &lsquo;{alias?.alias_text}&rsquo;?</AlertDialogTitle>
          <AlertDialogDescription>
            It will no longer be used to match payers.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-1">
          <Label htmlFor="retire-reason">Reason</Label>
          <Textarea
            id="retire-reason"
            value={reason}
            rows={3}
            maxLength={1000}
            aria-invalid={reasonError !== null}
            aria-describedby={reasonError ? "retire-reason-error" : undefined}
            onChange={(e) => setReason(e.target.value)}
          />
          {reasonError ? (
            <p id="retire-reason-error" role="alert" className="text-sm text-destructive">
              {reasonError}
            </p>
          ) : null}
        </div>
        {error ? <ErrorAlert error={error} title="Couldn't retire the alias" /> : null}
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button type="button" variant="destructive" disabled={pending} onClick={submit}>
            {pending ? "Retiring…" : "Retire alias"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
