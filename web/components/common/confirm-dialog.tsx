"use client";

import { useState, type ReactNode } from "react";

import { ActionButton } from "@/components/common/action-button";
import { useShellSession } from "@/components/common/shell-session";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Textarea } from "@/components/ui/textarea";
import { formatUtcStamp, highestRole } from "@/lib/roles";

const CONFIRM_VARIANT = { warn: "warn-solid", accent: "default", err: "destructive" } as const;

/**
 * An audited action: a required reason, a "Recorded as" line and the expected version.
 * The dialog stays open until the parent closes it, so `error` can be shown inline.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  tone = "warn",
  expectedVersion,
  reasonLabel = "Reason",
  reasonPlaceholder,
  pending = false,
  error,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  tone?: "warn" | "accent" | "err";
  expectedVersion?: number;
  reasonLabel?: string;
  reasonPlaceholder?: string;
  pending?: boolean;
  error?: ReactNode;
  onConfirm: (result: { reason: string }) => void | Promise<void>;
}) {
  const { me } = useShellSession();
  const [reason, setReason] = useState("");
  const trimmed = reason.trim();
  const role = highestRole(me);
  const actor = role ? `${me.display_name} · ${role}` : me.display_name;
  const version = expectedVersion !== undefined ? ` · expected version ${expectedVersion}` : "";

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setReason("");
        onOpenChange(next);
      }}
    >
      <AlertDialogContent
        className={
          tone === "warn" ? "border border-warn/40 shadow-[0_0_40px_-22px_var(--warn)]" : undefined
        }
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription render={<div />}>{body}</AlertDialogDescription>
        </AlertDialogHeader>
        <label className="grid gap-1.5 text-[13px] font-medium">
          {reasonLabel}
          <Textarea
            value={reason}
            placeholder={reasonPlaceholder}
            onChange={(event) => setReason(event.target.value)}
            disabled={pending}
            required
          />
        </label>
        <p className="font-mono text-label text-muted-foreground">
          Recorded as {actor} · {formatUtcStamp(new Date())} UTC{version}
        </p>
        {error ? (
          <div role="alert" className="text-[13px] text-err-ink">
            {error}
          </div>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
          <ActionButton
            variant={CONFIRM_VARIANT[tone]}
            disabled={trimmed === "" || pending}
            onClick={() => {
              void onConfirm({ reason: trimmed });
            }}
          >
            {confirmLabel}
          </ActionButton>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
