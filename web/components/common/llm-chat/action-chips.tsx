"use client";

import { SuggestionChip } from "@/components/common/filter-chip";
import { cn } from "@/lib/utils";

type SuggestionChipsProps = {
  chips: readonly string[];
  disabled?: boolean;
  onPick: (text: string) => void;
  /** One horizontally scrolling row (the narrow dock) instead of wrapping and centred. */
  scroll?: boolean;
  className?: string;
};

/** The suggestion-chips row; picking a chip sends it as a turn. No action handling lives here. */
export function ActionChips({ chips, disabled, onPick, scroll, className }: SuggestionChipsProps) {
  if (chips.length === 0) return null;
  return (
    <ul
      aria-label="Suggestions"
      className={cn(
        "flex gap-2",
        scroll ? "overflow-x-auto whitespace-nowrap" : "flex-wrap justify-center",
        className,
      )}
    >
      {chips.map((text) => (
        <li key={text} className="shrink-0">
          <SuggestionChip disabled={disabled} onClick={() => onPick(text)}>
            {text}
          </SuggestionChip>
        </li>
      ))}
    </ul>
  );
}
