"use client";

import { LogOutIcon } from "lucide-react";
import { useTheme } from "next-themes";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Me } from "@/lib/permissions";
import { highestRole, initials } from "@/lib/roles";

const THEMES = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
  { value: "system", label: "System" },
] as const;

/** The rail's user row: initials avatar, name and role. Opens the account menu with the theme. */
export function UserMenu({ me }: { me: Me }) {
  const { theme, setTheme } = useTheme();
  const role = highestRole(me);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="User menu"
        className="flex w-full items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-left hover:bg-white/5"
      >
        <span
          aria-hidden
          className="grid size-7 shrink-0 place-items-center rounded-full border border-line-strong bg-surface-3 text-[11px] font-medium"
        >
          {initials(me.display_name)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px]">{me.display_name}</span>
          <span className="block truncate font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            {role ?? "no role"}
          </span>
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex flex-col">
            <span className="text-sm font-medium text-foreground">{me.display_name}</span>
            {me.email ? <span className="text-xs font-normal">{me.email}</span> : null}
            <span className="text-xs font-normal">{me.roles.join(", ")}</span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel>Theme</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={theme ?? "dark"} onValueChange={setTheme}>
            {THEMES.map((option) => (
              <DropdownMenuRadioItem key={option.value} value={option.value}>
                {option.label}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <form method="post" action="/auth/sign-out">
          <button
            type="submit"
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent focus-visible:bg-accent"
          >
            <LogOutIcon className="size-4" /> Sign out
          </button>
        </form>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
