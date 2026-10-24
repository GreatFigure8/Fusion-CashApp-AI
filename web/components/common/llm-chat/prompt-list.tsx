"use client";

import { Command, CommandEmpty, CommandGroup, CommandItem, CommandList } from "@/components/ui/command";

import { PROMPT_LIST } from "./defaults";

type PromptListProps = {
  /** What was typed after the leading `/`. */
  query: string;
  onPick: (prompt: string) => void;
};

/** The `/` prompt list: sits above the composer; picking inserts the prompt text. */
export function PromptList({ query, onPick }: PromptListProps) {
  const q = query.trim().toLowerCase();
  const shown = PROMPT_LIST.filter((p) => q === "" || p.toLowerCase().includes(q));
  return (
    <div
      data-slot="prompt-list"
      className="absolute inset-x-0 bottom-full z-10 mb-2 overflow-hidden rounded-xl border border-line-strong bg-popover shadow-float"
    >
      <Command shouldFilter={false}>
        <CommandList>
          <CommandEmpty>No saved prompt matches.</CommandEmpty>
          <CommandGroup heading="Prompts">
            {shown.map((p) => (
              <CommandItem key={p} value={p} onSelect={() => onPick(p)}>
                {p}
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </Command>
    </div>
  );
}
