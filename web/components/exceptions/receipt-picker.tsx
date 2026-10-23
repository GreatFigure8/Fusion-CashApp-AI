"use client";

import { MonoLabel } from "@/components/common/mono-label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Schemas } from "@/lib/api/types";
import { formatMoney } from "@/lib/format";

import { useSheet } from "./sheet-context";

type Props = Readonly<{ receipts: readonly Schemas["CandidateReceiptOut"][] }>;

function optionLabel(receipt: Schemas["CandidateReceiptOut"]): string {
  const parts = [
    receipt.receipt_number,
    receipt.receipt_date ?? "—",
    formatMoney(receipt.remaining, receipt.currency),
  ];
  return `${parts.join(" · ")}${receipt.chosen ? " (system pick)" : ""}`;
}

/** Pick the receipt that pays this remittance. Shown only for `RECEIPT_AMBIGUOUS`. */
export function ReceiptPicker({ receipts }: Props): React.JSX.Element {
  const sheet = useSheet();
  const editable = sheet.canWork && sheet.sheet.editable;
  const selected = sheet.draft.receipt?.id;
  const items = receipts.map((r) => ({ value: String(r.receipt_id), label: optionLabel(r) }));

  return (
    <section className="grid gap-2" aria-labelledby="receipt-picker-title">
      <MonoLabel as="h3">
        <span id="receipt-picker-title">Receipt to use</span>
      </MonoLabel>
      <Select
        items={items}
        value={selected !== undefined ? String(selected) : null}
        disabled={!editable}
        onValueChange={(value) => {
          const receipt = receipts.find((r) => String(r.receipt_id) === value);
          sheet.setReceipt(
            receipt ? { id: receipt.receipt_id, number: receipt.receipt_number } : undefined,
          );
        }}
      >
        <SelectTrigger className="w-full font-mono" aria-labelledby="receipt-picker-title">
          <SelectValue placeholder="Choose a receipt" />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value} className="font-mono">
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {!editable ? (
        <p className="text-xs text-muted-foreground">Dequeue the item to pick a receipt.</p>
      ) : null}
    </section>
  );
}
