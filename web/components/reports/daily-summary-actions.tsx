"use client";

import { useRef, useState, useTransition } from "react";
import type * as React from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ApiError } from "@/lib/api/errors";
import { emailDailySummary, generateDailySummary } from "@/app/(shell)/reports/actions";
import { splitRecipients } from "@/lib/reports/schemas";
import { formatReportDate } from "@/lib/reports/format";

type Failure = Readonly<{ title: string; error: ApiError }>;

export function DailySummaryActions({ date }: { date: string }): React.JSX.Element {
  const [pending, startTransition] = useTransition();
  const [failure, setFailure] = useState<Failure | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [recipientText, setRecipientText] = useState("");
  const lastAttempt = useRef<(() => void) | null>(null);

  const runGenerate = (): void => {
    lastAttempt.current = runGenerate;
    setFailure(null);
    startTransition(async () => {
      const result = await generateDailySummary({ date });
      if (result.ok) toast.success("Daily summary generated");
      else
        setFailure({ title: "Couldn't generate the report.", error: result.error });
    });
  };

  const runEmail = (): void => {
    lastAttempt.current = runEmail;
    setFailure(null);
    const recipients = splitRecipients(recipientText);
    startTransition(async () => {
      const result = await emailDailySummary(
        recipients.length > 0 ? { date, recipients } : { date },
      );
      if (result.ok) {
        const n = result.value.emailed_to.length;
        toast.success(`Emailed to ${n} ${n === 1 ? "recipient" : "recipients"}`);
        setDialogOpen(false);
      } else {
        setFailure({ title: "Couldn't email the report.", error: result.error });
        setDialogOpen(false);
      }
    });
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <Button onClick={runGenerate} disabled={pending}>
          {pending ? "Working..." : "Generate now"}
        </Button>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger render={<Button variant="outline" disabled={pending} />}>
            Email to list…
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Email the daily summary</DialogTitle>
              <DialogDescription>
                Sends the {formatReportDate(date)} report with CSV and XLSX attached. Leave the box
                empty to use the configured list.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-2">
              <Label htmlFor="report-recipients">Recipients (optional)</Label>
              <Textarea
                id="report-recipients"
                value={recipientText}
                onChange={(e) => setRecipientText(e.target.value)}
                placeholder="name@example.com, other@example.com"
                rows={3}
              />
            </div>
            <DialogFooter>
              <Button onClick={runEmail} disabled={pending}>
                Send
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
      {failure ? (
        <Alert variant="destructive" role="alert">
          <AlertTitle>{failure.title}</AlertTitle>
          <AlertDescription>
            {failure.error.message}
            {failure.error.requestId ? ` (request id ${failure.error.requestId})` : ""}
            <Button
              variant="outline"
              size="sm"
              className="ml-2"
              onClick={() => lastAttempt.current?.()}
              disabled={pending}
            >
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}
