"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";

import { ErrorAlert } from "@/components/common/error-alert";
import { StatusBadge } from "@/components/common/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { Schemas } from "@/lib/api/types";
import { formatWorkItemId, humanizeEnum } from "@/lib/format";

import type { RemittanceExtraction } from "./edit-model";
import { LockControls } from "./lock-controls";
import { SheetProvider, useSheet } from "./sheet-context";

type Props = Readonly<{
  itemId: number;
  /** The signed-in user's subject, to tell my lock from someone else's. */
  me: string;
  canWork: boolean;
  item: Pick<Schemas["ItemOut"], "stage" | "state" | "version" | "payer_name">;
  lock: Schemas["LockInfoOut"] | null;
  final: RemittanceExtraction | null;
  /** The server-rendered body (RC-8): passed through, never re-rendered by this component. */
  children: ReactNode;
}>;

function Notices(): React.JSX.Element | null {
  const { sheet, requeueError } = useSheet();
  return (
    <>
      {sheet.notice?.kind === "moved_on" ? (
        <Alert>
          <AlertTitle>The line moved on</AlertTitle>
          <AlertDescription>
            This item is now {humanizeEnum(sheet.notice.state)} at {humanizeEnum(sheet.notice.stage)}
            . Nothing more to do here.
          </AlertDescription>
        </Alert>
      ) : null}
      {sheet.notice?.kind === "reasons_updated" ? (
        <Alert>
          <AlertTitle>The reasons were updated</AlertTitle>
          <AlertDescription>The system re-examined this item. Read the summary again.</AlertDescription>
        </Alert>
      ) : null}
      {requeueError ? <ErrorAlert error={requeueError} title="Couldn't requeue the item" /> : null}
    </>
  );
}

function Header({ itemId, payer, final }: Readonly<{ itemId: number; payer: string | null; final: RemittanceExtraction | null }>) {
  const { sheet } = useSheet();
  return (
    <SheetHeader className="gap-3 border-b pr-12">
      <div className="flex flex-wrap items-center gap-2">
        <SheetTitle className="font-mono">{formatWorkItemId(itemId)}</SheetTitle>
        <StatusBadge kind="item_state" value={sheet.state} />
        <span className="text-xs text-muted-foreground">{humanizeEnum(sheet.stage)}</span>
      </div>
      <SheetDescription>{payer ?? "Payer not read"}</SheetDescription>
      <LockControls final={final} />
    </SheetHeader>
  );
}

export function ExceptionSheet({
  itemId,
  me,
  canWork,
  item,
  lock,
  final,
  children,
}: Props): React.JSX.Element {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const close = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("item");
    const query = params.toString();
    router.replace((query ? `${pathname}?${query}` : pathname) as Route, { scroll: false });
  };

  return (
    <SheetProvider itemId={itemId} me={me} canWork={canWork} item={item} lock={lock}>
      <Sheet open onOpenChange={(open) => (open ? undefined : close())}>
        <SheetContent
          className="w-full overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-none lg:data-[side=right]:w-[60vw]"
          aria-label={`Exception ${formatWorkItemId(itemId)}`}
        >
          <Header itemId={itemId} payer={item.payer_name} final={final} />
          <div className="grid gap-5 px-4 pb-8">
            <Notices />
            {children}
          </div>
        </SheetContent>
      </Sheet>
    </SheetProvider>
  );
}
