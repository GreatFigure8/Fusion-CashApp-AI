import { ErrorAlert } from "@/components/common/error-alert";
import { EmptyState } from "@/components/common/empty-state";
import type { ApiError } from "@/lib/api/errors";
import { formatRelative } from "@/lib/format";
import type { Schemas } from "@/lib/api/types";

import { uiFor } from "./config-registry";
import { jsonValueSchema } from "./config-schemas";
import { formatConfigValue } from "./value-format";

function absolute(iso: string): string {
  return `${new Date(iso).toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function show(settingKey: string, raw: unknown): string {
  const ui = uiFor(settingKey);
  const parsed = jsonValueSchema.safeParse(raw);
  return formatConfigValue(ui.editor, parsed.success ? parsed.data : null, ui.unit);
}

/** The change log of one setting: who, when, old → new and the reason. */
export function HistoryList({
  settingKey,
  changes,
  error,
}: {
  settingKey: string;
  changes: readonly Schemas["ConfigChangeOut"][] | null;
  error: ApiError | null;
}) {
  if (error) return <ErrorAlert error={error} title="Couldn't load the history" />;
  if (!changes || changes.length === 0) {
    return (
      <EmptyState
        title="No changes yet."
        description="This setting has its default value."
      />
    );
  }
  return (
    <ol className="space-y-4">
      {changes.map((c) => (
        <li key={c.id} className="space-y-1 rounded-lg border p-3 text-sm">
          <p className="font-medium">{c.changed_by_name}</p>
          <p className="text-xs text-muted-foreground">
            <time dateTime={c.changed_at}>{absolute(c.changed_at)}</time> ·{" "}
            {formatRelative(c.changed_at)}
          </p>
          <p className="break-words">
            <span className="text-muted-foreground">{show(settingKey, c.old_value)}</span>
            {" → "}
            <span>{show(settingKey, c.new_value)}</span>
          </p>
          <p className="text-muted-foreground">Reason: {c.reason}</p>
        </li>
      ))}
    </ol>
  );
}
