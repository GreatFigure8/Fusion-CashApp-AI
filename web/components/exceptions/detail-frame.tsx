"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";

import { GlassPanel } from "@/components/common/glass-panel";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/hooks/use-media-query";

const CloseContext = createContext<(() => void) | null>(null);

/** Closes the detail by dropping `?item` from the URL. Used by the detail header. */
export function useDetailClose(): () => void {
  const close = useContext(CloseContext);
  if (!close) throw new Error("useDetailClose must be used inside <DetailFrame>");
  return close;
}

/** The detail container: a side panel at 1024 px and up, a full-width sheet below. */
export function DetailFrame({
  label,
  children,
}: Readonly<{ label: string; children: ReactNode }>): React.JSX.Element {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const wide = useMediaQuery("(min-width: 1024px)", true);

  const close = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("item");
    const query = params.toString();
    router.replace((query ? `${pathname}?${query}` : pathname) as Route, { scroll: false });
  };

  if (wide) {
    return (
      <CloseContext.Provider value={close}>
        <GlassPanel
          as="aside"
          aria-label={label}
          tone="accent"
          className="min-w-0 flex-[1_1_420px] self-start ring-1 ring-brand-hi/35"
        >
          {children}
        </GlassPanel>
      </CloseContext.Provider>
    );
  }
  return (
    <CloseContext.Provider value={close}>
      <Sheet open onOpenChange={(open) => (open ? undefined : close())}>
        <SheetContent
          showCloseButton={false}
          aria-label={label}
          className="w-full overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-none"
        >
          <SheetTitle className="sr-only">{label}</SheetTitle>
          <SheetDescription className="sr-only">Exception detail</SheetDescription>
          {children}
        </SheetContent>
      </Sheet>
    </CloseContext.Provider>
  );
}
