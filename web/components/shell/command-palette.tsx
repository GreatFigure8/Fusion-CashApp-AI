"use client";

import { SearchIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { searchItems, type SearchHit } from "@/components/shell/actions";
import { Button } from "@/components/ui/button";
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

/** ⌘K / Ctrl+K: jump to an item by WI id, receipt number or invoice number. */
export function CommandPalette() {
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

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="gap-2 text-muted-foreground"
        onClick={() => setOpen(true)}
        aria-label="Search items"
      >
        <SearchIcon /> <span className="hidden sm:inline">Search</span>
        <kbd className="hidden rounded border px-1 font-mono text-[10px] sm:inline">⌘K</kbd>
      </Button>
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
    </>
  );
}
