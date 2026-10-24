"use client";

import { useState } from "react";

import { ActionButton } from "@/components/common/action-button";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { Pill } from "@/components/common/pill";
import { THROTTLE_BOUNDS } from "@/lib/engine/schemas";

type Values = { perStage: number; applyPerReceipt: number };

function Slider({
  id,
  label,
  value,
  min,
  max,
  disabled,
  onChange,
}: Readonly<{
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  disabled: boolean;
  onChange: (v: number) => void;
}>) {
  return (
    <div className="grid gap-1">
      <div className="flex items-center justify-between font-mono text-xs">
        <label htmlFor={id}>{label}</label>
        <span>{value}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={1}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="accent-[var(--acc-hi)]"
      />
    </div>
  );
}

export function ThrottlePanel({
  initial,
  configVersion,
  enabled,
  canControl,
  onSave,
}: Readonly<{
  initial: Values;
  configVersion: number;
  enabled: boolean;
  canControl: boolean;
  onSave: (values: Values) => void;
}>) {
  // Re-seed when the server value changes (config version moves), without an effect.
  const [seed, setSeed] = useState({ version: configVersion, ...initial });
  const [values, setValues] = useState<Values>(initial);
  if (seed.version !== configVersion) {
    setSeed({ version: configVersion, ...initial });
    setValues(initial);
  }
  const changed =
    values.perStage !== initial.perStage || values.applyPerReceipt !== initial.applyPerReceipt;

  return (
    <GlassPanel as="section" aria-label="Throttle">
      <PanelHeader title="Throttle">
        <Pill tone="muted" mono>
          config v{configVersion}
        </Pill>
      </PanelHeader>
      <PanelBody className="grid gap-4">
        <Slider
          id="throttle-per-stage"
          label="concurrency.per_stage"
          value={values.perStage}
          min={THROTTLE_BOUNDS.perStage.min}
          max={THROTTLE_BOUNDS.perStage.max}
          disabled={!enabled}
          onChange={(perStage) => setValues((v) => ({ ...v, perStage }))}
        />
        <Slider
          id="throttle-apply-per-receipt"
          label="concurrency.apply_per_receipt"
          value={values.applyPerReceipt}
          min={THROTTLE_BOUNDS.applyPerReceipt.min}
          max={THROTTLE_BOUNDS.applyPerReceipt.max}
          disabled={!enabled}
          onChange={(applyPerReceipt) => setValues((v) => ({ ...v, applyPerReceipt }))}
        />
        <p className="text-xs text-soft">
          Fusion applies take about 6 s a line; this is the back-pressure.
        </p>
        <div>
          <ActionButton
            variant="warn"
            disabled={!enabled || !changed}
            onClick={() => onSave(values)}
          >
            {canControl ? "Save throttle…" : "Save throttle · needs admin"}
          </ActionButton>
        </div>
      </PanelBody>
    </GlassPanel>
  );
}
