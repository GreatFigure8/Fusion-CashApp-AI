import { StateCard } from "@/components/common/state-card";

import { ActionChips } from "./action-chips";
import { WELCOME_TITLE } from "./defaults";

type SuggestionsProps = {
  suggestions: readonly string[];
  disabled: boolean;
  onPick: (text: string) => void;
};

/** The empty-thread welcome. */
export function Suggestions({ suggestions, disabled, onPick }: SuggestionsProps) {
  return (
    <div data-slot="chat-suggestions" className="flex flex-col items-center gap-4 py-6">
      <StateCard kind="empty" label="Empty · welcome" headline={WELCOME_TITLE} className="w-full max-w-xl" />
      <ActionChips chips={suggestions} disabled={disabled} onPick={onPick} />
    </div>
  );
}
