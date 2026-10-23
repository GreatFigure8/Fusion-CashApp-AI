import { ErrorAlert } from "@/components/common/error-alert";
import { EmptyState } from "@/components/common/empty-state";
import type { ApiError } from "@/lib/api/errors";
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

/** The change log: who, when, `key old → new` and the quoted reason. Serves one key or all keys. */
export function HistoryList({
  changes,
  error,
  topVersion,
}: {
  changes: readonly Schemas["ConfigChangeOut"][] | null;
  error: ApiError | null;
  /** When set, rows are numbered v{topVersion}, v{topVersion-1}, … (newest first). */
  topVersion?: number;
}) {
  if (error) return <ErrorAlert error={error} title="Couldn't load the history" />;
  if (!changes || changes.length === 0) {
    return <EmptyState title="No changes yet." description="Nothing has been changed from the seed values." />;
  }
  return (
    <ol className="space-y-3">
      {changes.map((c, index) => (
        <li key={c.id} className="space-y-1 text-sm">
          <p className="font-mono text-[11px] text-faint">
            {topVersion === undefined ? null : <span className="text-brand-ink">v{topVersion - index} · </span>}
            <time dateTime={c.changed_at}>{absolute(c.changed_at)}</time> · {c.changed_by_name}
          </p>
          <p className="font-mono text-[13px] break-words">
            {c.key}{" "}
            <span className="text-muted-foreground">{show(c.key, c.old_value)}</span>
            {" → "}
            <span>{show(c.key, c.new_value)}</span>
          </p>
          <p className="text-muted-foreground">&ldquo;{c.reason}&rdquo;</p>
        </li>
      ))}
    </ol>
  );
}
