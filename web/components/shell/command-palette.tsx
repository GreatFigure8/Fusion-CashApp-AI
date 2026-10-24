"use client";

import { MessageSquareIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { focusAssistantDock } from "@/components/common/llm-chat/dock";
import { searchItems, type SearchHit } from "@/components/shell/actions";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { formatWorkItemId, humanizeEnum, parseWorkItemId } from "@/lib/format";

const DEBOUNCE_MS = 250;
const KIND_LABEL: Record<SearchHit["kind"], string> = {
  item: "Item",
  receipt: "Receipt",
  invoice: "Invoice",
};

type Found = { q: string; hits: SearchHit[] };

type PaletteValue = { open: () => void };

const PaletteContext = createContext<PaletteValue | null>(null);

/** Opens the palette from anywhere in the shell (the top bar search field, the assistant). */
export function useCommandPalette(): PaletteValue {
  const value = useContext(PaletteContext);
  if (value === null) throw new Error("useCommandPalette must be used inside CommandPaletteProvider");
  return value;
}

/** ⌘K / Ctrl+K: jump to an item by WI id, receipt number or invoice number. */
export function CommandPaletteProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Found | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const trimmed = query.trim();
  useEffect(() => {
    if (trimmed === "") return;
    let current = true;
    const timer = setTimeout(() => {
      void searchItems({ q: trimmed }).then((result) => {
        if (current) setFound({ q: trimmed, hits: result.ok ? result.value : [] });
      });
    }, DEBOUNCE_MS);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [trimmed]);

  const go = (itemId: number) => {
    setOpen(false);
    setQuery("");
    router.push(`/items/${itemId}`);
  };

  const direct = /^WI-\d+$/i.test(trimmed) ? parseWorkItemId(trimmed) : null;
  const hits = found !== null && found.q === trimmed ? found.hits : [];

  const openPalette = useCallback(() => setOpen(true), []);
  const value = useMemo<PaletteValue>(() => ({ open: openPalette }), [openPalette]);

  return (
    <PaletteContext.Provider value={value}>
      {children}
      <CommandDialog
        open={open}
        onOpenChange={setOpen}
        title="Search items"
        description="Jump to an item by WI id, receipt number or invoice number."
      >
        <Command shouldFilter={false}>
          <CommandInput
            value={query}
            onValueChange={setQuery}
            placeholder="WI id, receipt number or invoice number…"
          />
          <CommandList>
            <CommandGroup heading="Assistant">
              <CommandItem
                value="ask-the-assistant"
                onSelect={() => {
                  setOpen(false);
                  setQuery("");
                  // After the dialog closes, so the dialog's focus return doesn't win.
                  setTimeout(focusAssistantDock, 0);
                }}
              >
                <MessageSquareIcon /> Ask the assistant
              </CommandItem>
            </CommandGroup>
            {trimmed !== "" && hits.length === 0 && direct === null ? (
              <CommandEmpty>No matching item.</CommandEmpty>
            ) : null}
            {direct !== null ? (
              <CommandGroup heading="Go to">
                <CommandItem value={`go-${direct}`} onSelect={() => go(direct)}>
                  Go to {formatWorkItemId(direct)}
                </CommandItem>
              </CommandGroup>
            ) : null}
            {hits.length > 0 ? (
              <CommandGroup heading="Items">
                {hits.map((hit) => (
                  <CommandItem
                    key={`${hit.item_id}-${hit.kind}`}
                    value={`${hit.item_id}-${hit.kind}`}
                    onSelect={() => go(hit.item_id)}
                  >
                    <span className="font-mono">{formatWorkItemId(hit.item_id)}</span>
                    <span className="text-muted-foreground">
                      {KIND_LABEL[hit.kind]} {hit.match}
                    </span>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {humanizeEnum(hit.stage)} · {humanizeEnum(hit.state)}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            ) : null}
          </CommandList>
        </Command>
      </CommandDialog>
    </PaletteContext.Provider>
  );
}
