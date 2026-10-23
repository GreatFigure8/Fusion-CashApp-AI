"use client";

import { Money } from "@/components/common/money";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import type { Schemas } from "@/lib/api/types";

import { useSheet } from "./sheet-context";

type Props = Readonly<{ receipts: readonly Schemas["CandidateReceiptOut"][] }>;

/** Pick the receipt that pays this remittance. Shown only for `RECEIPT_AMBIGUOUS`. */
export function ReceiptPicker({ receipts }: Props): React.JSX.Element {
  const sheet = useSheet();
  const editable = sheet.canWork && sheet.sheet.editable;
  const selected = sheet.draft.receipt?.id;

  return (
    <section className="grid gap-2" aria-labelledby="receipt-picker-title">
      <h4 id="receipt-picker-title" className="text-sm font-medium">
        Which receipt pays this?
      </h4>
      <RadioGroup
        value={selected !== undefined ? String(selected) : ""}
        onValueChange={(value) => {
          const receipt = receipts.find((r) => String(r.receipt_id) === value);
          sheet.setReceipt(
            receipt ? { id: receipt.receipt_id, number: receipt.receipt_number } : undefined,
          );
        }}
        disabled={!editable}
      >
        {receipts.map((receipt) => {
          const id = `receipt-${receipt.receipt_id}`;
          return (
            <div key={receipt.receipt_id} className="flex items-center gap-3">
              <RadioGroupItem id={id} value={String(receipt.receipt_id)} />
              <Label htmlFor={id} className="flex flex-wrap items-center gap-x-3 font-normal">
                <span className="font-mono">{receipt.receipt_number}</span>
                <span className="text-muted-foreground">{receipt.receipt_date ?? "—"}</span>
                <Money amount={receipt.remaining} currency={receipt.currency} />
                {receipt.chosen ? (
                  <span className="text-xs text-muted-foreground">system pick</span>
                ) : null}
              </Label>
            </div>
          );
        })}
      </RadioGroup>
      {!editable ? (
        <p className="text-xs text-muted-foreground">Dequeue the item to pick a receipt.</p>
      ) : null}
    </section>
  );
}
