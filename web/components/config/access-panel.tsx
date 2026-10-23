"use client";

import { useState } from "react";

import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { Pill } from "@/components/common/pill";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Schemas } from "@/lib/api/types";

import { GROUP_ROLE_KEY } from "./config-registry";
import { useStaging } from "./config-staging-provider";
import { SaveFooter } from "./save-footer";
import { SettingRow } from "./setting-row";
import { stagedCount } from "./staging";

/** Fixed copy describing each role's permission set. */
const CAN: Readonly<Record<string, string>> = {
  ADMIN: "Everything, incl. engine control and config",
  OPERATOR: "Work items, lab replays, reports",
  VIEWER: "Reports",
};

/**
 * Groups-to-roles table. "Map a group" reveals the group-role editor, which stages and audits
 * through the same row, footer and review as every other setting.
 */
export function AccessPanel({
  groupRoles,
  latestChange,
  nextVersion,
}: {
  groupRoles: Schemas["GroupRolesResponse"];
  latestChange: Schemas["ConfigChangeOut"] | null;
  nextVersion: number;
}) {
  const { state, canEdit } = useStaging();
  const [editing, setEditing] = useState(false);
  const count = stagedCount(state);

  return (
    <GlassPanel as="section" aria-label="Access: groups to roles">
      <PanelHeader title="Access: groups to roles">
        {count > 0 ? (
          <Pill tone="warn">
            {count} unsaved {count === 1 ? "change" : "changes"}
          </Pill>
        ) : null}
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!canEdit}
          aria-expanded={editing}
          onClick={() => setEditing((v) => !v)}
        >
          Map a group
        </Button>
      </PanelHeader>
      <PanelBody flush>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Identity-domain group</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Can</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groupRoles.mappings.map((m) => (
              <TableRow key={`${m.group_name}:${m.role}`}>
                <TableCell className="font-mono text-[13px]">{m.group_name}</TableCell>
                <TableCell>
                  <Pill tone={m.role === "ADMIN" ? "accent" : "muted"}>{m.role}</Pill>
                </TableCell>
                <TableCell className="text-muted-foreground">{CAN[m.role] ?? ""}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {editing || count > 0 ? (
          <SettingRow
            entry={{
              key: GROUP_ROLE_KEY,
              // The API's PUT has no version check (last writer wins). The newest change id stands
              // in for a version: 0 means "default", and it moves with every save.
              version: latestChange?.id ?? 0,
              value: groupRoles.mappings,
              description:
                "Maps identity-domain groups to app roles. At least one group must map to ADMIN.",
              last_changed_at: latestChange?.changed_at ?? groupRoles.updated_at,
              last_changed_by: latestChange?.changed_by_name ?? null,
            }}
          />
        ) : null}
      </PanelBody>
      <SaveFooter nextVersion={nextVersion} />
    </GlassPanel>
  );
}
