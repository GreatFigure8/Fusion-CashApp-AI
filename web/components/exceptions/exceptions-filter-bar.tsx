"use client";

import type { Route } from "next";
import { format, parseISO } from "date-fns";
import { CalendarIcon, Check, ChevronsUpDown } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import type { DateRange } from "react-day-picker";

import {
  filtersToSearchParams,
  isFiltered,
  type ErrorCode,
  type ExceptionFilters,
  type Stage,
} from "@/app/(shell)/exceptions/_lib/search-params";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { humanizeEnum } from "@/lib/format";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 300;
const ALL_STAGES = "__all";

type Props = Readonly<{
  filters: ExceptionFilters;
  errorCodeOptions: readonly ErrorCode[];
  stageOptions: readonly Stage[];
  /** Holds `classification:override`: the archived switch is shown only then. */
  canSeeArchived: boolean;
}>;

/** A text field that writes the URL after a pause and adopts URL changes made elsewhere. */
function useDebouncedField(urlValue: string | undefined, push: (value: string | undefined) => void) {
  const current = urlValue ?? "";
  const [text, setText] = useState(current);
  const [seen, setSeen] = useState(current);
  const [pushed, setPushed] = useState(current);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  if (current !== seen) {
    setSeen(current);
    if (current !== pushed) {
      setText(current);
      setPushed(current);
    }
  }

  useEffect(() => () => clearTimeout(timer.current), []);

  const onChange = (value: string) => {
    setText(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const next = value.trim();
      setPushed(next);
      push(next === "" ? undefined : next);
    }, DEBOUNCE_MS);
  };
  return [text, onChange] as const;
}

export function ExceptionsFilterBar({
  filters,
  errorCodeOptions,
  stageOptions,
  canSeeArchived,
}: Props): React.JSX.Element {
  const router = useRouter();
  const pathname = usePathname();
  const ids = useId();

  const update = (patch: Partial<ExceptionFilters>) => {
    const next: ExceptionFilters = { ...filters, ...patch, page: 1 };
    const query = filtersToSearchParams(next).toString();
    router.replace((query ? `${pathname}?${query}` : pathname) as Route, { scroll: false });
  };

  const [q, setQ] = useDebouncedField(filters.q, (value) => update({ q: value }));
  const [amountMin, setAmountMin] = useDebouncedField(filters.amountMin, (value) =>
    update({ amountMin: value }),
  );
  const [amountMax, setAmountMax] = useDebouncedField(filters.amountMax, (value) =>
    update({ amountMax: value }),
  );

  const range: DateRange | undefined =
    filters.dateFrom || filters.dateTo
      ? {
          from: filters.dateFrom ? parseISO(filters.dateFrom) : undefined,
          to: filters.dateTo ? parseISO(filters.dateTo) : undefined,
        }
      : undefined;
  const rangeLabel =
    filters.dateFrom || filters.dateTo
      ? `${filters.dateFrom ?? "…"} to ${filters.dateTo ?? "…"}`
      : "Payment date";

  const toggleCode = (code: ErrorCode) => {
    const has = filters.errorCodes.includes(code);
    update({
      errorCodes: has ? filters.errorCodes.filter((c) => c !== code) : [...filters.errorCodes, code],
    });
  };

  const stageItems = [
    { value: ALL_STAGES, label: "All stages" },
    ...stageOptions.map((s) => ({ value: s, label: humanizeEnum(s) })),
  ];

  return (
    <div className="flex flex-wrap items-end gap-3" role="search" aria-label="Filter exceptions">
      <div className="grid gap-1">
        <Label htmlFor={`${ids}-q`} className="text-xs text-muted-foreground">
          Search
        </Label>
        <Input
          id={`${ids}-q`}
          type="search"
          placeholder="Payer, invoice, receipt, WI"
          className="w-56"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <div className="grid gap-1">
        <Label htmlFor={`${ids}-min`} className="text-xs text-muted-foreground">
          Amount
        </Label>
        <div className="flex items-center gap-1">
          <Input
            id={`${ids}-min`}
            inputMode="decimal"
            placeholder="Min"
            aria-label="Minimum amount"
            className="w-24 font-mono"
            value={amountMin}
            onChange={(e) => setAmountMin(e.target.value)}
          />
          <span aria-hidden className="text-muted-foreground">
            –
          </span>
          <Input
            inputMode="decimal"
            placeholder="Max"
            aria-label="Maximum amount"
            className="w-24 font-mono"
            value={amountMax}
            onChange={(e) => setAmountMax(e.target.value)}
          />
        </div>
      </div>

      <div className="grid gap-1">
        <span className="text-xs text-muted-foreground">Date range</span>
        <Popover>
          <PopoverTrigger render={<Button variant="outline" className="justify-start" />}>
            <CalendarIcon />
            <span className={cn(!range && "text-muted-foreground")}>{rangeLabel}</span>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar
              mode="range"
              selected={range}
              onSelect={(next) =>
                update({
                  dateFrom: next?.from ? format(next.from, "yyyy-MM-dd") : undefined,
                  dateTo: next?.to ? format(next.to, "yyyy-MM-dd") : undefined,
                })
              }
            />
          </PopoverContent>
        </Popover>
      </div>

      <div className="grid gap-1">
        <span className="text-xs text-muted-foreground">Error code</span>
        <Popover>
          <PopoverTrigger render={<Button variant="outline" className="w-48 justify-between" />}>
            <span className="truncate">
              {filters.errorCodes.length === 0
                ? "Any error"
                : `${filters.errorCodes.length} selected`}
            </span>
            <ChevronsUpDown className="opacity-50" />
          </PopoverTrigger>
          <PopoverContent className="w-72 p-0" align="start">
            <Command>
              <CommandInput placeholder="Search error codes" />
              <CommandList>
                <CommandEmpty>No error code matches.</CommandEmpty>
                <CommandGroup>
                  {errorCodeOptions.map((code) => (
                    <CommandItem key={code} value={code} onSelect={() => toggleCode(code)}>
                      <Check
                        className={cn(
                          "size-4",
                          filters.errorCodes.includes(code) ? "" : "opacity-0",
                        )}
                      />
                      <span className="font-mono text-xs">{code}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      </div>

      <div className="grid gap-1">
        <span className="text-xs text-muted-foreground">Stage</span>
        <Select
          items={stageItems}
          value={filters.stage ?? ALL_STAGES}
          onValueChange={(value) =>
            update({ stage: value && value !== ALL_STAGES ? (value as Stage) : undefined })
          }
        >
          <SelectTrigger className="w-44" aria-label="Stage">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {stageItems.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-wrap items-center gap-4 pb-1.5">
        <Label className="gap-2 font-normal">
          <Switch
            checked={filters.lockedByMe}
            onCheckedChange={(checked) => update({ lockedByMe: checked })}
          />
          Locked by me
        </Label>
        <Label className="gap-2 font-normal">
          <Switch
            checked={filters.includeAutoApplied}
            onCheckedChange={(checked) => update({ includeAutoApplied: checked })}
          />
          Show auto-applied
        </Label>
        {canSeeArchived ? (
          <Label className="gap-2 font-normal">
            <Switch
              checked={filters.includeArchived}
              onCheckedChange={(checked) => update({ includeArchived: checked })}
            />
            Show archived
          </Label>
        ) : null}
      </div>

      {isFiltered(filters) ? (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            const query = filters.item ? `?item=${filters.item}` : "";
            router.replace(`${pathname}${query}` as Route, { scroll: false });
          }}
        >
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}
