"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import { formatRelative } from "@/lib/format";

/** "Changed by {name} {relative}" or "Default value"; opens the history sheet via `?history=<key>`. */
export function ChangedByLink({
  settingKey,
  name,
  at,
  version,
}: {
  settingKey: string;
  name: string | null;
  at: string | null;
  version: number;
}) {
  const pathname = usePathname();
  const params = useSearchParams();
  const next = new URLSearchParams(params.toString());
  next.set("history", settingKey);
  const text =
    version === 0 || !at
      ? "Default value"
      : `Changed by ${name ?? "unknown"} ${formatRelative(at)}`;
  return (
    <Link
      href={`${pathname}?${next.toString()}` as Route}
      scroll={false}
      className="text-xs text-muted-foreground underline-offset-2 hover:underline"
    >
      {text}
    </Link>
  );
}
