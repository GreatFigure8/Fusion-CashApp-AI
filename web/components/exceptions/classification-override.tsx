"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";

import { overrideClassificationAction } from "@/app/(shell)/exceptions/_lib/actions";
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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ApiError } from "@/lib/api/errors";

type Props = Readonly<{ itemId: number }>;

/** For an archived item: tell the system it is a remittance after all, so it re-enters the line. */
export function ClassificationOverride({ itemId }: Props): React.JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [pending, startTransition] = useTransition();

  const confirm = () =>
    startTransition(async () => {
      const result = await overrideClassificationAction({ itemId, reason: reason.trim() });
      if (!result.ok) {
        setError(result.error);
        return;
      }
      toast.success("Marked as a remittance");
      setOpen(false);
      setError(null);
      router.refresh();
    });

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger render={<Button size="sm" variant="outline" />}>
        This is a remittance
      </AlertDialogTrigger>
      <AlertDialogContent className="sm:max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>Treat this as a remittance?</AlertDialogTitle>
          <AlertDialogDescription>
            The item leaves the archive and goes on to extraction. Say why the classification was
            wrong.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="grid gap-1.5">
          <Label htmlFor="override-reason">Reason (required)</Label>
          <Textarea
            id="override-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            maxLength={1000}
          />
        </div>
        {error ? <ErrorAlert error={error} title="Couldn't override the classification" /> : null}
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button onClick={confirm} disabled={pending || reason.trim() === ""}>
            {pending ? "Saving…" : "Mark as remittance"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
