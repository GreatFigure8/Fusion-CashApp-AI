"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type SelectOption = Readonly<{ value: string; label: string }>;

/** The one labelled select used by every editor. */
export function OptionSelect({
  value,
  options,
  onChange,
  label,
  disabled,
  invalid,
  className,
}: {
  value: string;
  options: readonly SelectOption[];
  onChange: (next: string) => void;
  label: string;
  disabled?: boolean;
  invalid?: boolean;
  className?: string;
}) {
  return (
    <Select
      value={value}
      items={[...options]}
      disabled={disabled}
      onValueChange={(next) => {
        if (typeof next === "string") onChange(next);
      }}
    >
      <SelectTrigger aria-label={label} aria-invalid={invalid} className={className}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
