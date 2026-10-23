"use client";

import { Check, ChevronsUpDown } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Schemas } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { useSheet } from "./sheet-context";

type Props = Readonly<{
  customer: Schemas["CustomerContextOut"] | null;
  invoices: readonly Schemas["InvoiceContextOut"][];
}>;

type Option = { account: string; label: string };

/** Pick the customer account to resolve to. Shown only for `CUSTOMER_*` errors. */
export function CustomerPicker({ customer, invoices }: Props): React.JSX.Element {
  const sheet = useSheet();
  const editable = sheet.canWork && sheet.sheet.editable;
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");

  const options = useMemo(() => {
    const found = new Map<string, Option>();
    if (customer) {
      found.set(customer.account_number, {
        account: customer.account_number,
        label: `${customer.account_number} · ${customer.name} (anchor)`,
      });
      for (const rel of customer.relationships) {
        found.set(rel.account_number, {
          account: rel.account_number,
          label: `${rel.account_number} · ${rel.name ?? "related account"} (related)`,
        });
      }
    }
    for (const invoice of invoices) {
      const account = invoice.bill_to_customer;
      if (account && !found.has(account)) {
        found.set(account, { account, label: `${account} · bills ${invoice.number}` });
      }
    }
    return [...found.values()];
  }, [customer, invoices]);

  const selected = sheet.draft.customer;

  const choose = (account: string | undefined) => {
    sheet.setCustomer(account);
    setOpen(false);
  };

  return (
    <section className="grid gap-2" aria-labelledby="customer-picker-title">
      <h4 id="customer-picker-title" className="text-sm font-medium">
        Which customer account?
      </h4>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          render={
            <Button
              variant="outline"
              className="w-full justify-between sm:w-80"
              disabled={!editable}
            />
          }
        >
          <span className="truncate font-mono">{selected ?? "Choose an account"}</span>
          <ChevronsUpDown className="opacity-50" />
        </PopoverTrigger>
        <PopoverContent className="w-80 p-0" align="start">
          <Command>
            <CommandInput placeholder="Search accounts" />
            <CommandList>
              <CommandEmpty>No known account matches.</CommandEmpty>
              <CommandGroup>
                {options.map((option) => (
                  <CommandItem
                    key={option.account}
                    value={option.label}
                    onSelect={() => choose(option.account)}
                  >
                    <Check
                      className={cn("size-4", selected === option.account ? "" : "opacity-0")}
                    />
                    {option.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      <div className="grid gap-1 sm:w-80">
        <Label htmlFor="customer-free-text" className="text-xs text-muted-foreground">
          Or type an account number
        </Label>
        <Input
          id="customer-free-text"
          className="font-mono"
          value={typed}
          disabled={!editable}
          onChange={(e) => {
            setTyped(e.target.value);
            sheet.setCustomer(e.target.value.trim() || undefined);
          }}
        />
      </div>
      {!editable ? (
        <p className="text-xs text-muted-foreground">Dequeue the item to pick an account.</p>
      ) : null}
    </section>
  );
}
