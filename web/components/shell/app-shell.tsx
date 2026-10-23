"use client";

import { DiamondIcon } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, type ReactNode } from "react";

import { LiveIndicator } from "@/components/common/live-indicator";
import { Breadcrumbs } from "@/components/shell/breadcrumbs";
import { CommandPalette } from "@/components/shell/command-palette";
import { EnvBadge } from "@/components/shell/env-badge";
import { FlowStreamProvider, useFlowStream } from "@/components/shell/flow-stream";
import { visibleNav } from "@/components/shell/nav";
import { UserMenu } from "@/components/shell/user-menu";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import type { Me } from "@/lib/permissions";

function SidebarNav({ me }: { me: Me }) {
  const pathname = usePathname();
  const { summary } = useFlowStream();
  const needsPerson = summary?.kpis.needs_person ?? null;
  return (
    <SidebarMenu>
      {visibleNav(me).map((item) => (
        <SidebarMenuItem key={item.href}>
          <SidebarMenuButton
            render={<Link href={item.href as Route} />}
            isActive={pathname === item.href || pathname.startsWith(`${item.href}/`)}
            tooltip={item.label}
          >
            <item.icon />
            <span>{item.label}</span>
          </SidebarMenuButton>
          {item.href === "/exceptions" && needsPerson !== null ? (
            <SidebarMenuBadge data-testid="exceptions-count">{needsPerson}</SidebarMenuBadge>
          ) : null}
        </SidebarMenuItem>
      ))}
    </SidebarMenu>
  );
}

function ShellLiveIndicator() {
  const { status, retries, retry } = useFlowStream();
  return <LiveIndicator status={status} retries={retries} onRetry={retry} />;
}

/** The sidebar, header and page frame around every signed-in page. */
export function AppShell({
  me,
  envLabel,
  children,
}: {
  me: Me;
  envLabel: string;
  children: ReactNode;
}) {
  return (
    <SidebarProvider>
      <FlowStreamProvider>
        <Sidebar collapsible="icon">
          <SidebarHeader>
            <Link href="/flow" className="flex items-center gap-2 px-2 py-1.5 font-semibold">
              <DiamondIcon aria-hidden className="size-4" />
              <span className="group-data-[collapsible=icon]:sr-only">CashApp</span>
            </Link>
          </SidebarHeader>
          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupContent>
                <SidebarNav me={me} />
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
          <SidebarFooter>
            <ShellLiveIndicator />
          </SidebarFooter>
          <SidebarRail />
        </Sidebar>
        <SidebarInset className="min-w-0">
          <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
            <SidebarTrigger />
            <Separator orientation="vertical" className="h-4" />
            <div className="min-w-0 flex-1 overflow-hidden">
              <Suspense fallback={null}>
                <Breadcrumbs />
              </Suspense>
            </div>
            <CommandPalette />
            <EnvBadge label={envLabel} />
            <UserMenu me={me} />
          </header>
          <div className="min-w-0 flex-1 overflow-x-hidden p-4">{children}</div>
        </SidebarInset>
      </FlowStreamProvider>
    </SidebarProvider>
  );
}
