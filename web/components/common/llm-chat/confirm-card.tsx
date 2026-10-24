"use client";

import { useId, useState } from "react";

import { ActionButton } from "@/components/common/action-button";
import { MonoLabel } from "@/components/common/mono-label";
import { Pill } from "@/components/common/pill";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import type { ConfirmDecision } from "./chat-reducer";
import { MAX_REASON_CHARS, type ConfirmPreview } from "./chat-schemas";

type ConfirmCardProps = {
  callId: string;
  tool: string;
  preview: ConfirmPreview;
  decision: ConfirmDecision;
  onConfirm: (callId: string, reason: string) => void;
  onCancel: (callId: string) => void;
};

const DIFF_TONE = { "+": "text-ok", "-": "text-err", " ": "text-soft" } as const;

/** Nothing runs before Confirm: this card only reports the person's choice. */
export function ConfirmCard({ callId, tool, preview, decision, onConfirm, onCancel }: ConfirmCardProps) {
  const [reason, setReason] = useState("");
  const reasonId = useId();
  const pending = decision === "pending";
  const canConfirm = pending && reason.trim().length > 0;

  const rows: { label: string; value: string }[] = [
    { label: "What", value: preview.what },
    { label: "Before", value: preview.before },
    { label: "After", value: preview.after },
    { label: "Who", value: preview.who },
    ...preview.details,
  ];

  return (
    <section
      aria-label={`Confirm ${tool}`}
      data-slot="confirm-card"
      data-decision={decision}
      className="rounded-xl border border-warn/40 bg-surface-2 p-4 shadow-[0_0_40px_-22px_var(--warn)]"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <MonoLabel className="text-warn">CONFIRM A CHANGE</MonoLabel>
        <Pill tone="locked" mono>
          Audited
        </Pill>
      </div>
      <dl className="grid grid-cols-[88px_1fr] gap-x-3 gap-y-1.5 text-[13px]">
        {rows.map((r) => (
          <div key={`${r.label}:${r.value}`} className="contents">
            <dt className="font-mono text-[11.5px] uppercase tracking-wider text-soft">{r.label}</dt>
            <dd className="min-w-0 break-words">{r.value}</dd>
          </div>
        ))}
      </dl>
      {preview.diff.length > 0 ? (
        <pre className="mt-3 overflow-x-auto rounded-md bg-surface-3 p-2 font-mono text-[12px]">
          {preview.diff.map((l, i) => (
            <div key={`${i}:${l.text}`} className={cn(DIFF_TONE[l.op])}>
              {l.op} {l.text}
            </div>
          ))}
        </pre>
      ) : null}

      {pending ? (
        <div className="mt-3 flex flex-col gap-2">
          <label htmlFor={reasonId} className="font-mono text-[11.5px] uppercase tracking-wider text-soft">
            Reason (required)
          </label>
          <Textarea
            id={reasonId}
            value={reason}
            maxLength={MAX_REASON_CHARS}
            rows={2}
            placeholder={preview.reason_prompt}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex items-center gap-2">
            <ActionButton
              type="button"
              variant="warn-solid"
              disabled={!canConfirm}
              onClick={() => onConfirm(callId, reason.trim())}
            >
              Confirm
            </ActionButton>
            <ActionButton type="button" variant="ghost" onClick={() => onCancel(callId)}>
              Cancel
            </ActionButton>
          </div>
        </div>
      ) : (
        <p className="mt-3 font-mono text-[12px] uppercase tracking-wider text-soft">
          {decision === "cancelled" ? "Cancelled" : decision === "sending" ? "Confirmed, running" : "Confirmed"}
        </p>
      )}
    </section>
  );
}
