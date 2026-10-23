"use client";

import type { ReactNode } from "react";

import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { Pill } from "@/components/common/pill";
import type { Schemas } from "@/lib/api/types";

import { useStaging } from "./config-staging-provider";
import { SaveFooter } from "./save-footer";
import { SettingRow } from "./setting-row";
import { stagedCount } from "./staging";

/**
 * One card for a group (or for search results): header with the unsaved-change pill, optional
 * extra content above the rows, the rows, and the save footer. One copy serves every group.
 */
export function GroupCard({
  title,
  description,
  entries,
  nextVersion,
  extra,
}: {
  title: string;
  description?: string;
  entries: readonly Schemas["ConfigEntry"][];
  nextVersion: number;
  extra?: ReactNode;
}) {
  const { state } = useStaging();
  const count = stagedCount(state);
  return (
    <GlassPanel as="section" aria-label={title}>
      <PanelHeader title={title}>
        {count > 0 ? (
          <Pill tone="warn">
            {count} unsaved {count === 1 ? "change" : "changes"}
          </Pill>
        ) : null}
      </PanelHeader>
      {description ? (
        <p className="px-4 pb-2 text-sm text-muted-foreground">{description}</p>
      ) : null}
      {extra}
      <PanelBody flush>
        {entries.map((entry) => (
          <SettingRow key={entry.key} entry={entry} />
        ))}
      </PanelBody>
      <SaveFooter nextVersion={nextVersion} />
    </GlassPanel>
  );
}
