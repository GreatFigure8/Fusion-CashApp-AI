import Link from "next/link";

import { cn } from "@/lib/utils";

import { CONFIG_TABS, type ConfigTabId } from "./config-registry";

export function ConfigTabs({ active }: { active: ConfigTabId }) {
  return (
    <nav
      aria-label="Configuration sections"
      className="flex gap-1 overflow-x-auto rounded-xl border bg-card p-2 lg:w-52 lg:shrink-0 lg:flex-col lg:self-start lg:overflow-visible"
    >
      {CONFIG_TABS.map((tab) => (
        <Link
          key={tab.id}
          href={`/config?tab=${tab.id}`}
          aria-current={tab.id === active ? "page" : undefined}
          className={cn(
            "rounded-lg px-3 py-1.5 text-sm whitespace-nowrap transition-colors hover:bg-muted",
            tab.id === active && "bg-muted font-medium",
          )}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
