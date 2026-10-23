"use client";

import type { ReactNode } from "react";

import { ShellSessionProvider } from "@/components/common/shell-session";
import { CommandPaletteProvider } from "@/components/shell/command-palette";
import { FlowStreamProvider } from "@/components/shell/flow-stream";
import { MobileNavBar, NavRail } from "@/components/shell/nav-rail";
import type { Me } from "@/lib/permissions";

/**
 * The frame around every signed-in page: dotted ground, glass rail, main column, status footer
 * and an optional dock for the assistant.
 */
export function AppShell({
  me,
  env,
  sampleData,
  footer,
  dock,
  children,
}: {
  me: Me;
  env: Me["env"];
  sampleData: boolean;
  footer: ReactNode;
  dock?: ReactNode;
  children: ReactNode;
}) {
  return (
    <ShellSessionProvider me={me} env={env} sampleData={sampleData}>
      <FlowStreamProvider>
        <CommandPaletteProvider>
          <div className="bg-blueprint min-h-screen p-4">
            <MobileNavBar me={me} />
            <div className="mt-4 flex flex-wrap gap-4 lg:mt-0">
              <NavRail me={me} />
              <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-4">
                <main className="flex min-w-0 flex-col gap-4">{children}</main>
                {footer}
              </div>
            </div>
            {dock ? (
              <div className="mx-auto mt-4 w-[min(880px,100%)]" data-slot="shell-dock">
                {dock}
              </div>
            ) : null}
          </div>
        </CommandPaletteProvider>
      </FlowStreamProvider>
    </ShellSessionProvider>
  );
}
