"use client";

import { useState, useTransition } from "react";

import { runRetentionPurgeDryRun } from "@/app/(shell)/config/actions";
import { ErrorAlert } from "@/components/common/error-alert";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";

type Report = Schemas["PurgeReportResponse"];

const FIELDS: readonly (readonly [keyof Report, string])[] = [
  ["artifacts", "Artifacts"],
  ["parts", "Parts"],
  ["readings", "Readings"],
  ["adjudications", "Adjudications"],
  ["history_payloads", "History payloads"],
  ["objects_deleted", "Objects deleted"],
  ["objects_kept_shared", "Objects kept (shared)"],
  ["resumed", "Resumed"],
  ["skipped", "Skipped"],
];

/** Previews what a purge would remove. It can never run a real purge. */
export function PurgeDryRun() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [pending, startTransition] = useTransition();

  function run() {
    startTransition(async () => {
      const res = await runRetentionPurgeDryRun({});
      if (res.ok) {
        setReport(res.value);
        setError(null);
      } else {
        setError(res.error);
      }
    });
  }

  return (
    <section aria-labelledby="purge-heading" className="space-y-3 rounded-xl border bg-card p-4">
      <div className="space-y-0.5">
        <h3 id="purge-heading" className="text-sm font-medium">
          Purge preview
        </h3>
        <p className="text-sm text-muted-foreground">
          Shows what the current retention settings would delete. Nothing is deleted.
        </p>
      </div>
      <Button type="button" variant="outline" disabled={pending} onClick={run}>
        {pending ? "Running…" : "Run purge (dry run)"}
      </Button>
      {error ? <ErrorAlert error={error} title="Couldn't run the dry run" /> : null}
      {report ? (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
          {FIELDS.map(([field, label]) => (
            <div key={field}>
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-mono">{String(report[field])}</dd>
            </div>
          ))}
          <div>
            <dt className="text-muted-foreground">Ran at</dt>
            <dd>
              <time dateTime={report.ran_at}>{new Date(report.ran_at).toISOString().slice(0, 19).replace("T", " ")} UTC</time>
            </dd>
          </div>
        </dl>
      ) : null}
    </section>
  );
}
