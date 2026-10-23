"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useId } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

/** The "Show applied items" checkbox for the top bar. Writes `include_auto_applied`, resets paging. */
export function ShowAppliedToggle(): React.JSX.Element {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const id = useId();
  const checked = ["1", "true"].includes(searchParams.get("include_auto_applied") ?? "");

  const onChange = (next: boolean) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next) params.set("include_auto_applied", "1");
    else params.delete("include_auto_applied");
    params.delete("page");
    const query = params.toString();
    router.replace((query ? `${pathname}?${query}` : pathname) as Route, { scroll: false });
  };

  return (
    <div className="flex items-center gap-2 text-[13px]">
      <Checkbox id={id} checked={checked} onCheckedChange={(value) => onChange(value === true)} />
      <Label htmlFor={id} className="font-normal text-muted-foreground">
        Show applied items
      </Label>
    </div>
  );
}
