"use client";

import { MenuIcon } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { GlassPanel } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import { NavCount } from "@/components/shell/nav-counts";
import { visibleNav } from "@/components/shell/nav";
import { UserMenu } from "@/components/shell/user-menu";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import type { Me } from "@/lib/permissions";
import { cn } from "@/lib/utils";

function BrandRow() {
  return (
    <Link href={"/dashboard" as Route} className="flex items-center gap-2.5 px-1 py-1">
      <span
        aria-hidden
        className="grid size-7 place-items-center rounded-lg bg-brand font-mono text-xs text-white shadow-[0_0_20px_-4px_#4f7cff]"
      >
        CA
      </span>
      <span className="font-semibold">CashApp</span>
      <MonoLabel className="ml-auto">AI</MonoLabel>
    </Link>
  );
}

function NavLinks({ me, onNavigate }: { me: Me; onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <ul className="grid gap-1">
      {visibleNav(me).map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <li key={item.href}>
            <Link
              href={item.href as Route}
              aria-current={active ? "page" : undefined}
              onClick={onNavigate}
              className={cn(
                "flex min-h-10 items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-sm transition-colors",
                active
                  ? "bg-brand-soft text-brand-ink shadow-[inset_0_0_0_1px_#4f7cff66,0_0_28px_-10px_#4f7cff]"
                  : "text-foreground/80 hover:bg-white/[0.04]",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "grid h-[22px] w-[26px] shrink-0 place-items-center rounded-md border font-mono text-[10px]",
                  active ? "border-brand-hi" : "border-line-strong text-muted-foreground",
                )}
              >
                {item.code}
              </span>
              <span>{item.label}</span>
              {item.countSource ? (
                <NavCount
                  source={item.countSource}
                  testId={item.href === "/exceptions" ? "exceptions-count" : undefined}
                />
              ) : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function RailContent({ me, onNavigate }: { me: Me; onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col gap-3">
      <BrandRow />
      <nav aria-label="Primary" className="flex-1">
        <NavLinks me={me} onNavigate={onNavigate} />
      </nav>
      <div className="border-t border-line pt-2">
        <UserMenu me={me} />
      </div>
    </div>
  );
}

/** The glass left rail, shown from 1024px up. */
export function NavRail({ me }: { me: Me }) {
  return (
    <GlassPanel
      as="aside"
      aria-label="Navigation"
      className="sticky top-4 hidden max-h-[calc(100vh-2rem)] min-w-[200px] flex-[1_1_200px] self-start p-3 lg:block"
    >
      <RailContent me={me} />
    </GlassPanel>
  );
}

/** Below 1024px: a brand bar with a menu button that opens the rail in a sheet. */
export function MobileNavBar({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  return (
    <GlassPanel as="header" className="flex items-center gap-2 p-2 lg:hidden">
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger render={<Button variant="ghost" size="icon" aria-label="Open navigation" />}>
          <MenuIcon />
        </SheetTrigger>
        <SheetContent side="left" className="w-72 p-3">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">Go to a page or open your account menu.</SheetDescription>
          <RailContent
            me={me}
            onNavigate={() => {
              setOpen(false);
            }}
          />
        </SheetContent>
      </Sheet>
      <BrandRow />
    </GlassPanel>
  );
}
