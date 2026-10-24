"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { saveConfigChanges } from "@/app/(shell)/config/actions";
import { ErrorAlert } from "@/components/common/error-alert";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { DiffBlock } from "@/components/common/diff-block";
import { Button } from "@/components/ui/button";
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
      return <span className="text-ok-ink">✓ Saved</span>;
    case "conflict":
      return (
        <span className="text-err-ink">
          ✗ {result.message}{" "}
          <Button type="button" variant="outline" size="xs" onClick={() => onReload(result.key)}>
            Reload
          </Button>
        </span>
      );
    case "invalid":
      return <span className="text-err-ink">✗ Invalid: {result.message}</span>;
    case "failed":
      return <span className="text-err-ink">✗ {result.error.message}</span>;
  }
}

/** Lists each staged change as old → new, asks for one reason, saves, and shows per-key results. */
export function ReviewDialog({
  open,
  onOpenChange,
  nextVersion,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  nextVersion: number;
}) {
  const router = useRouter();
  const { state, dispatch } = useStaging();
  const [error, setError] = useState<ApiError | null>(null);
  const [results, setResults] = useState<Record<string, KeyResult>>({});
  const [pending, startTransition] = useTransition();

  const diff = stagedDiff(state);
  const blocked = Object.values(state.errors).some((e) => e.length > 0);

  function submit({ reason }: { reason: string }) {
    const parsedReason = reasonSchema.safeParse(reason);
    if (!parsedReason.success) {
      setError(null);
      return;
    }
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
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Save as v${nextVersion}`}
      body={
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Each change is saved on its own. One reason is recorded for all of them.
          </p>
          <ul className="max-h-64 space-y-2 overflow-y-auto text-sm">
            {diff.map((d) => (
              <li key={d.key} className="space-y-1">
                <DiffBlock
                  lines={[
                    { op: "-", text: `${d.key} ${formatConfigValue(d.editor, d.oldValue, d.unit)}` },
                    { op: "+", text: `${d.key} ${formatConfigValue(d.editor, d.newValue, d.unit)}` },
                  ]}
                />
                {results[d.key] ? <ResultLine result={results[d.key]!} onReload={reload} /> : null}
              </li>
            ))}
            {resultList
              .filter((r) => !diff.some((d) => d.key === r.key))
              .map((r) => (
                <li key={r.key}>
                  <ResultLine result={r} onReload={reload} />
                </li>
              ))}
          </ul>
          {blocked ? (
            <p role="alert" className="text-sm text-err-ink">
              Fix the highlighted settings before saving.
            </p>
          ) : null}
        </div>
      }
      confirmLabel={`Save as v${nextVersion}`}
      tone="accent"
      expectedVersion={nextVersion - 1}
      pending={pending || blocked || diff.length === 0}
      error={error ? <ErrorAlert error={error} title="Couldn't save the changes" /> : null}
      onConfirm={submit}
    />
  );
}
