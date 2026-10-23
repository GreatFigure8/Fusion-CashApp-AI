import type { Schemas } from "@/lib/api/types";

import { CONFIG_TAB_NOTES, keysForTab, uiFor, type ConfigTabId } from "./config-registry";
import { SettingRow } from "./setting-row";

/** Renders every registry row of a tab. One copy serves all the settings tabs. */
export function SettingsPanel({
  entries,
  tab,
}: {
  entries: readonly Schemas["ConfigEntry"][];
  tab: ConfigTabId;
}) {
  const rows = keysForTab(entries, tab);
  const main = rows.filter((e) => uiFor(e.key).section !== "other");
  const other = rows.filter((e) => uiFor(e.key).section === "other");
  const note = CONFIG_TAB_NOTES[tab];
  return (
    <div className="space-y-4">
      {note ? (
        <p className="rounded-lg border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          {note}
        </p>
      ) : null}
      {main.map((entry) => (
        <SettingRow key={entry.key} entry={entry} />
      ))}
      {other.length > 0 ? (
        <>
          <h2 className="pt-2 text-sm font-semibold text-muted-foreground">Other settings</h2>
          {other.map((entry) => (
            <SettingRow key={entry.key} entry={entry} />
          ))}
        </>
      ) : null}
    </div>
  );
}
