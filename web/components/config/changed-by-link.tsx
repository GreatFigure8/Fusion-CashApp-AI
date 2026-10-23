"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

/** The last-changed text as a link that opens the history sheet via `?history=<key>`. */
export function ChangedByLink({ settingKey, label }: { settingKey: string; label: string }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const next = new URLSearchParams(params.toString());
  next.set("history", settingKey);
  return (
    <Link
      href={`${pathname}?${next.toString()}` as Route}
      scroll={false}
      className="font-mono text-[11px] text-faint underline-offset-2 hover:underline"
    >
      {label}
    </Link>
  );
}
