"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import {
  editFormSchema,
  LINE_KINDS,
  toFormValues,
  type EditFormValues,
  type RemittanceExtraction,
} from "./edit-model";
import { useSheet } from "./sheet-context";

type Props = Readonly<{ final: RemittanceExtraction }>;

const HEADER_FIELDS = [
  ["payer_name", "Payer"],
  ["remittance_reference", "Reference"],
  ["payment_amount", "Amount"],
  ["currency", "Currency"],
  ["payment_date", "Payment date"],
] as const;

export function EditForm({ final }: Props): React.JSX.Element {
  const sheet = useSheet();
  const editable = sheet.canWork && sheet.sheet.editable;
  // A server refresh hands over a new object each time; only a changed extraction resets the form.
  const extractionKey = JSON.stringify(final);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const initial = useMemo(() => toFormValues(final), [extractionKey]);

  const form = useForm<EditFormValues>({
    resolver: zodResolver(editFormSchema),
    defaultValues: initial,
    mode: "onChange",
  });
  const { fields, append, remove } = useFieldArray({ control: form.control, name: "lines" });
  const watched = useWatch({ control: form.control });

  const { setBaseline, setAfter } = sheet;
  useEffect(() => {
    setBaseline(initial);
    form.reset(initial);
  }, [initial, setBaseline, form]);

  useEffect(() => {
    const parsed = editFormSchema.safeParse(watched);
    // Only a valid form is offered to the requeue dialog; the errors show inline meanwhile.
    if (parsed.success) setAfter(parsed.data);
  }, [watched, setAfter]);

  const errors = form.formState.errors;

  return (
    <form className="grid gap-4" onSubmit={(e) => e.preventDefault()} aria-label="Extracted data">
      <fieldset disabled={!editable} className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-2">
          {HEADER_FIELDS.map(([name, label]) => (
            <div key={name} className="grid gap-1">
              <Label htmlFor={`edit-${name}`}>{label}</Label>
              <Input
                id={`edit-${name}`}
                aria-invalid={errors[name] ? true : undefined}
                className={name === "payer_name" ? "" : "font-mono"}
                {...form.register(name)}
              />
              {errors[name] ? (
                <p className="text-xs text-destructive">{errors[name]?.message}</p>
              ) : null}
            </div>
          ))}
        </div>

        <div className="grid gap-2">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium">Lines</h4>
            {editable ? (
              <Button
                type="button"
                size="xs"
                variant="outline"
                onClick={() =>
                  append({
                    line_no: Math.max(0, ...fields.map((f) => f.line_no)) + 1,
                    kind: "INVOICE",
                    transaction_number: "",
                    amount_paid: "",
                    discount_claimed: "",
                  })
                }
              >
                <Plus /> Add line
              </Button>
            ) : null}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="w-10 pb-1 font-normal">#</th>
                  <th className="w-32 pb-1 font-normal">Kind</th>
                  <th className="pb-1 font-normal">Invoice / credit memo</th>
                  <th className="w-28 pb-1 font-normal">Amount paid</th>
                  <th className="w-24 pb-1 font-normal">Discount</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {fields.map((field, index) => {
                  const lineErrors = errors.lines?.[index];
                  return (
                    <tr key={field.id} className="align-top">
                      <td className="py-1 font-mono text-muted-foreground">{field.line_no}</td>
                      <td className="py-1 pr-2">
                        <select
                          aria-label={`Line ${field.line_no} kind`}
                          className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm disabled:opacity-50"
                          {...form.register(`lines.${index}.kind`)}
                        >
                          {LINE_KINDS.map((kind) => (
                            <option key={kind} value={kind}>
                              {kind}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="py-1 pr-2">
                        <Input
                          aria-label={`Line ${field.line_no} invoice`}
                          aria-invalid={lineErrors?.transaction_number ? true : undefined}
                          className="font-mono"
                          {...form.register(`lines.${index}.transaction_number`)}
                        />
                        {lineErrors?.transaction_number ? (
                          <p className="text-xs text-destructive">
                            {lineErrors.transaction_number.message}
                          </p>
                        ) : null}
                      </td>
                      <td className="py-1 pr-2">
                        <Input
                          aria-label={`Line ${field.line_no} amount`}
                          aria-invalid={lineErrors?.amount_paid ? true : undefined}
                          className="text-right font-mono"
                          {...form.register(`lines.${index}.amount_paid`)}
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <Input
                          aria-label={`Line ${field.line_no} discount`}
                          aria-invalid={lineErrors?.discount_claimed ? true : undefined}
                          className="text-right font-mono"
                          {...form.register(`lines.${index}.discount_claimed`)}
                        />
                      </td>
                      <td className="py-1">
                        {editable ? (
                          <Button
                            type="button"
                            size="icon-sm"
                            variant="ghost"
                            aria-label={`Remove line ${field.line_no}`}
                            onClick={() => remove(index)}
                          >
                            <Trash2 />
                          </Button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!editable ? (
            <p className="text-xs text-muted-foreground">
              Dequeue the item to edit these values.
            </p>
          ) : null}
        </div>
      </fieldset>
    </form>
  );
}
