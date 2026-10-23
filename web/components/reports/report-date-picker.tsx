"use client";

import { CalendarIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type * as React from "react";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatReportDate } from "@/lib/reports/format";

type Props =
  | Readonly<{ mode: "single"; date: string; max: string }>
  | Readonly<{ mode: "range"; from: string; to: string; max: string }>;

/** ISO day -> a Date at local midnight (the calendar works in local days). */
function toLocal(iso: string): Date {
  const [y = 1970, m = 1, d = 1] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function toIso(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

export function ReportDatePicker(props: Props): React.JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const after = toLocal(props.max);

  const go = (query: Record<string, string>): void => {
    const q = new URLSearchParams(query);
    router.push(`/reports?${q.toString()}`);
    setOpen(false);
  };

  const label =
    props.mode === "single"
      ? formatReportDate(props.date)
      : `${formatReportDate(props.from)} to ${formatReportDate(props.to)}`;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={<Button variant="outline" aria-label={`Report date: ${label}`} />}
      >
        <CalendarIcon aria-hidden="true" />
        {label}
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        {props.mode === "single" ? (
          <Calendar
            mode="single"
            selected={toLocal(props.date)}
            defaultMonth={toLocal(props.date)}
            disabled={{ after }}
            onSelect={(d: Date | undefined) => {
              if (d) go({ tab: "daily", date: toIso(d) });
            }}
          />
        ) : (
          <Calendar
            mode="range"
            selected={{ from: toLocal(props.from), to: toLocal(props.to) }}
            defaultMonth={toLocal(props.from)}
            disabled={{ after }}
            onSelect={(r: DateRange | undefined) => {
              if (r?.from && r.to) go({ tab: "partial", from: toIso(r.from), to: toIso(r.to) });
            }}
          />
        )}
      </PopoverContent>
    </Popover>
  );
}
