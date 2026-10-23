"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

import type { ChatActionHandler, ChatActionSpec, ProposedAction } from "./chat-schemas";

type ActionChipsProps = {
  proposed: readonly ProposedAction[];
  specs: readonly ChatActionSpec[];
  /** Without a handler the chips are shown disabled. */
  onAction?: ChatActionHandler;
};

/** A chip per proposed action. Nothing runs until the person confirms in the dialog. */
export function ActionChips({ proposed, specs, onAction }: ActionChipsProps) {
  const [pending, setPending] = useState<ProposedAction | null>(null);
  const [running, setRunning] = useState(false);

  const specFor = (id: string) => specs.find((s) => s.id === id);
  const pendingSpec = pending ? specFor(pending.id) : undefined;

  const confirm = async () => {
    if (!pending || !pendingSpec || !onAction) return;
    setRunning(true);
    try {
      const result = await onAction(pending.id, pending.args);
      if (result.ok) {
        toast.success(`${pendingSpec.label} done`);
      } else {
        const id = result.error.requestId ? ` (request ${result.error.requestId})` : "";
        toast.error(`${pendingSpec.label} failed: ${result.error.message}${id}`);
      }
    } catch {
      toast.error(`${pendingSpec.label} failed`);
    } finally {
      setRunning(false);
      setPending(null);
    }
  };

  const visible = proposed.filter((p) => specFor(p.id) !== undefined);
  if (visible.length === 0) return null;

  return (
    <>
      <ul className="mt-2 flex flex-wrap gap-2" aria-label="Suggested actions">
        {visible.map((p) => {
          const spec = specFor(p.id);
          return (
            <li key={p.id} className="flex flex-col items-start gap-0.5">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!onAction}
                onClick={() => setPending(p)}
              >
                {spec?.label}
              </Button>
              {p.label !== p.id ? (
                <span className="text-xs text-muted-foreground">{p.label}</span>
              ) : null}
            </li>
          );
        })}
      </ul>
      <AlertDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open && !running) setPending(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pendingSpec?.confirm ?? `Run "${pendingSpec?.label ?? ""}"?`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pending && pending.label !== pending.id ? pending.label : "Check before acting."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={running}>Cancel</AlertDialogCancel>
            <AlertDialogAction disabled={running} onClick={() => void confirm()}>
              Confirm
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
