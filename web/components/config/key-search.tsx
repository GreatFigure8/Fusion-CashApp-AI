"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { MonoLabel } from "@/components/common/mono-label";
import { Input } from "@/components/ui/input";

/** Writes `?q=` (debounced) and keeps the other params, so the group stays selected. */
export function KeySearch({ initial }: { initial: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [text, setText] = useState(initial);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  function update(next: string) {
    setText(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const query = new URLSearchParams(params.toString());
      if (next.trim() === "") query.delete("q");
      else query.set("q", next.trim());
      query.delete("history");
      const qs = query.toString();
      router.replace((qs ? `${pathname}?${qs}` : pathname) as Route, { scroll: false });
    }, 200);
  }

  return (
    <label className="flex items-center gap-2">
      <MonoLabel>Find</MonoLabel>
      <Input
        type="search"
        value={text}
        maxLength={100}
        placeholder="Find a setting key"
        aria-label="Find a setting key"
        className="h-8 w-56 font-mono text-[13px]"
        onChange={(e) => update(e.target.value)}
      />
    </label>
  );
}
