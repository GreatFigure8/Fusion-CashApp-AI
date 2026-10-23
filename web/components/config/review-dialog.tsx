"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { saveConfigChanges } from "@/app/(shell)/config/actions";
import { ErrorAlert } from "@/components/common/error-alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ApiError } from "@/lib/api/errors";

import { GROUP_ROLE_KEY } from "./config-registry";
import { useStaging } from "./config-staging-provider";
import { groupRolesSchema, reasonSchema } from "./config-schemas";
import { stagedDiff, type KeyResult } from "./staging";
import { formatConfigValue } from "./value-format";

function ResultLine({
  result,
  onReload,
}: {
  result: KeyResult;
  onReload: (key: string) => void;
}) {
  switch (result.outcome) {
    case "saved":
      return <span className="text-status-success">✓ Saved</span>;
    case "conflict":
      return (
        <span className="text-destructive">
          ✗ {result.message}{" "}
          <Button type="button" variant="outline" size="xs" onClick={() => onReload(result.key)}>
            Reload
          </Button>
        </span>
      );
    case "invalid":
      return <span className="text-destructive">✗ Invalid: {result.message}</span>;
    case "failed":
      return <span className="text-destructive">✗ {result.error.message}</span>;
  }
}

/** Lists each staged change as old → new, asks for one reason, saves, and shows per-key results. */
export function ReviewDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const { state, dispatch } = useStaging();
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [results, setResults] = useState<Record<string, KeyResult>>({});
  const [pending, startTransition] = useTransition();

  const diff = stagedDiff(state);
  const blocked = Object.values(state.errors).some((e) => e.length > 0);

  function submit() {
    const parsedReason = reasonSchema.safeParse(reason);
    if (!parsedReason.success) {
      setReasonError(parsedReason.error.issues[0]?.message ?? "Enter a reason.");
      return;
    }
    setReasonError(null);
    setError(null);
    const roleRow = diff.find((d) => d.key === GROUP_ROLE_KEY);
    const mappings = roleRow ? groupRolesSchema.safeParse(roleRow.newValue) : null;
    startTransition(async () => {
      const res = await saveConfigChanges({
        reason: parsedReason.data,
        changes: diff
          .filter((d) => d.key !== GROUP_ROLE_KEY)
          .map((d) => ({ key: d.key, value: d.newValue, expected_version: d.expectedVersion })),
        groupRoles: mappings?.success ? { mappings: mappings.data } : undefined,
      });
      if (!res.ok) {
        setError(res.error);
        return;
      }
      const saved = res.value.results;
      dispatch({ type: "results", results: saved });
      setResults(Object.fromEntries(saved.map((r) => [r.key, r])));
      if (saved.every((r) => r.outcome === "saved")) {
        setReason("");
        setResults({});
        onOpenChange(false);
      }
    });
  }

  function reload(key: string) {
    dispatch({ type: "unstage", key });
    setResults((prev) => {
      const { [key]: _gone, ...rest } = prev;
      void _gone;
      return rest;
    });
    router.refresh();
  }

  const resultList = Object.values(results).filter((r) => r.outcome !== "saved");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Review and save</DialogTitle>
          <DialogDescription>
            Each change is saved on its own. One reason is recorded for all of them.
          </DialogDescription>
        </DialogHeader>
        <ul className="max-h-64 space-y-2 overflow-y-auto text-sm">
          {diff.map((d) => (
            <li key={d.key} className="rounded-lg border p-2">
              <p className="font-medium">{d.label}</p>
              <p className="break-words">
                <span className="text-muted-foreground">
                  {formatConfigValue(d.editor, d.oldValue, d.unit)}
                </span>
                {" → "}
                {formatConfigValue(d.editor, d.newValue, d.unit)}
              </p>
              {results[d.key] ? (
                <p className="mt-1">
                  <ResultLine result={results[d.key]!} onReload={reload} />
                </p>
              ) : null}
            </li>
          ))}
          {resultList
            .filter((r) => !diff.some((d) => d.key === r.key))
            .map((r) => (
              <li key={r.key} className="rounded-lg border p-2">
                <ResultLine result={r} onReload={reload} />
              </li>
            ))}
        </ul>
        <div className="space-y-1">
          <Label htmlFor="config-reason">Reason</Label>
          <Textarea
            id="config-reason"
            value={reason}
            aria-invalid={reasonError !== null}
            aria-describedby={reasonError ? "config-reason-error" : undefined}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            maxLength={1000}
          />
          {reasonError ? (
            <p id="config-reason-error" role="alert" className="text-sm text-destructive">
              {reasonError}
            </p>
          ) : null}
        </div>
        {error ? <ErrorAlert error={error} title="Couldn't save the changes" /> : null}
        {blocked ? (
          <p role="alert" className="text-sm text-destructive">
            Fix the highlighted settings before saving.
          </p>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button type="button" disabled={pending || diff.length === 0 || blocked} onClick={submit}>
            {pending ? "Saving…" : "Save changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
