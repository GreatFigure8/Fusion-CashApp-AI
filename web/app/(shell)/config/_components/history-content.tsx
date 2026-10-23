import { uiFor } from "@/components/config/config-registry";
import { HistoryList } from "@/components/config/history-list";
import { HistorySheet } from "@/components/config/history-sheet";

import { loadHistory } from "../_lib/load-config";

/** The history sheet for one key; its list is rendered on the server and passed in as children. */
export async function HistoryContent({ settingKey }: { settingKey: string }) {
  const result = await loadHistory(settingKey);
  return (
    <HistorySheet title={`History: ${uiFor(settingKey).label}`}>
      <HistoryList
        changes={result.ok ? result.value.items : null}
        error={result.ok ? null : result.error}
      />
    </HistorySheet>
  );
}
