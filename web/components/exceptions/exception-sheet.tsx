"use client";

import { XIcon } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { ErrorAlert } from "@/components/common/error-alert";
import { StatusBadge } from "@/components/common/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { Schemas } from "@/lib/api/types";
import { formatMoney, formatWorkItemId, humanizeEnum } from "@/lib/format";

import { DetailFrame, useDetailClose } from "./detail-frame";
import type { RemittanceExtraction } from "./edit-model";
import { LockConflictCard } from "./lock-conflict-card";
import { LockActions, LockStatus } from "./lock-controls";
import { reasonLabel } from "./reason";
import { SheetProvider, useSheet } from "./sheet-context";

type Props = Readonly<{
  itemId: number;
  /** The signed-in user's subject, to tell my lock from someone else's. */
  me: string;
  canWork: boolean;
  item: Pick<
    Schemas["ItemOut"],
    "stage" | "state" | "version" | "payer_name" | "amount" | "currency" | "last_error_code"
  >;
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

function Header({
  itemId,
  item,
}: Readonly<{ itemId: number; item: Props["item"] }>) {
  const { sheet } = useSheet();
  const close = useDetailClose();
  const money = item.amount && item.currency ? ` · ${formatMoney(item.amount, item.currency)}` : "";
  return (
    <header className="flex items-start gap-3 border-b border-line px-[18px] py-3.5">
      <div className="grid min-w-0 flex-1 gap-1">
        <p className="font-mono text-xs text-muted-foreground">
          {formatWorkItemId(itemId)}
          {money}
        </p>
        <h2 className="text-[17px] font-semibold tracking-[-0.01em]">
          {item.last_error_code ? reasonLabel(item.last_error_code) : "Needs a person"}
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <StatusBadge kind="item_state" value={sheet.state} />
          <span>{humanizeEnum(sheet.stage)}</span>
          <span>{item.payer_name ?? "Payer not read"}</span>
        </div>
      </div>
      <Button variant="ghost" size="icon-sm" aria-label="Close" onClick={close}>
        <XIcon />
      </Button>
    </header>
  );
}

function Body({
  itemId,
  item,
  final,
  children,
}: Readonly<{
  itemId: number;
  item: Props["item"];
  final: RemittanceExtraction | null;
  children: ReactNode;
}>) {
  const [conflictDismissed, setConflictDismissed] = useState(false);
  return (
    <>
      <Header itemId={itemId} item={item} />
      <div className="grid gap-5 px-[18px] py-4">
        <LockConflictCard
          dismissed={conflictDismissed}
          onDismiss={() => setConflictDismissed(true)}
        />
        <LockStatus />
        <Notices />
        {children}
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
          <LockActions final={final} errorCode={item.last_error_code} />
          <Link
            href={`/items/${itemId}` as Route}
            className="ml-auto text-sm underline-offset-4 hover:underline"
          >
            Full history
          </Link>
        </div>
      </div>
    </>
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
  return (
    <SheetProvider itemId={itemId} me={me} canWork={canWork} item={item} lock={lock}>
      <DetailFrame label={`Item ${formatWorkItemId(itemId)}`}>
        <Body itemId={itemId} item={item} final={final}>
          {children}
        </Body>
      </DetailFrame>
    </SheetProvider>
  );
}
