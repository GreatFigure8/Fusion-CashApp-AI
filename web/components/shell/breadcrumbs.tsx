"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Fragment } from "react";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { formatWorkItemId, humanizeEnum, parseWorkItemId } from "@/lib/format";

export type Crumb = { label: string; href: string | null };

const TOP_LEVEL: Record<string, string> = {
  flow: "Flow",
  exceptions: "Exceptions",
  reports: "Reports",
  config: "Config",
};

/** `Flow / Match receipt / WI-20481` from the path, plus `?from=<STAGE>` on item pages. */
export function buildCrumbs(pathname: string, from: string | null): Crumb[] {
  const [first, second] = pathname.split("/").filter(Boolean);
  if (first === undefined) return [];

  if (first === "items" && second !== undefined) {
    const id = parseWorkItemId(second);
    const label = id === null ? second : formatWorkItemId(id);
    const crumbs: Crumb[] = [{ label: "Flow", href: "/flow" }];
    if (from && /^[A-Z_]+$/.test(from)) {
      crumbs.push({ label: humanizeEnum(from), href: `/flow/${from.toLowerCase()}` });
    }
    crumbs.push({ label, href: null });
    return crumbs;
  }

  const top = TOP_LEVEL[first] ?? humanizeEnum(first);
  if (second === undefined) return [{ label: top, href: null }];
  return [
    { label: top, href: `/${first}` },
    { label: humanizeEnum(second), href: null },
  ];
}

export function Breadcrumbs() {
  const pathname = usePathname();
  const from = useSearchParams().get("from");
  const crumbs = buildCrumbs(pathname, from);
  return (
    <Breadcrumb>
      <BreadcrumbList>
        {crumbs.map((crumb, index) => (
          <Fragment key={`${crumb.label}-${index}`}>
            {index > 0 ? <BreadcrumbSeparator /> : null}
            <BreadcrumbItem>
              {crumb.href ? (
                <BreadcrumbLink render={<Link href={crumb.href as Route} />}>{crumb.label}</BreadcrumbLink>
              ) : (
                <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
              )}
            </BreadcrumbItem>
          </Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
