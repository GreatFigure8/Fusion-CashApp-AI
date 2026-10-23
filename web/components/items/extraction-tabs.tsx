"use client";

import { GlassPanel } from "@/components/common/glass-panel";
import { Pill } from "@/components/common/pill";
import { SOURCE_TAG, sourceTone } from "@/components/items/source-tag";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useHighlight } from "@/components/items/highlight-context";
import { extractionRows, type ExtractionRow } from "@/components/items/extraction-rows";
import type { Schemas } from "@/lib/api/types";
import { humanizeEnum } from "@/lib/format";

type Extraction = Schemas["ExtractionOut"];

function ConfidenceBar({ value }: { value: number }) {
  const percent = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2" title={`Confidence ${percent}%`}>
      <Progress value={percent} aria-label={`Confidence ${percent}%`} className="w-16 flex-col gap-0" />
      <span className="w-9 text-right text-xs text-muted-foreground tabular-nums">{percent}%</span>
    </div>
  );
}

function RowsTable({
  rows,
  provenance,
}: {
  rows: ExtractionRow[];
  provenance: Record<string, string> | null;
}) {
  const { active, setActive } = useHighlight();
  return (
    <Table className="text-[13px]">
      <TableHeader>
        <TableRow>
          <TableHead className="h-8 text-xs text-muted-foreground">Field</TableHead>
          <TableHead className="h-8 text-xs text-muted-foreground">Value</TableHead>
          {provenance ? <TableHead className="h-8 text-xs text-muted-foreground">From</TableHead> : null}
          <TableHead className="h-8 text-xs text-muted-foreground">Confidence</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => {
          const tag = provenance ? provenance[row.path] : undefined;
          return (
            <TableRow
              key={row.path}
              data-field={row.path}
              data-active={active === row.path ? "true" : undefined}
              className="data-[active=true]:bg-muted"
              onMouseEnter={() => setActive(row.path)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(row.path)}
              onBlur={() => setActive(null)}
              tabIndex={0}
            >
              <TableCell className="text-muted-foreground">{row.label}</TableCell>
              <TableCell className="font-mono whitespace-normal break-all">{row.value}</TableCell>
              {provenance ? (
                <TableCell>
                  {tag ? (
                    <Pill tone={sourceTone(tag)} mono>
                      {SOURCE_TAG[tag] ?? tag}
                    </Pill>
                  ) : null}
                </TableCell>
              ) : null}
              <TableCell>
                <ConfidenceBar value={row.confidence} />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function ReaderPane({ reading, name }: { reading: Extraction["reader_a"]; name: string }) {
  if (!reading) return <p className="p-3 text-sm text-muted-foreground">{name} produced no reading.</p>;
  return (
    <div className="flex flex-col gap-2">
      <p className="px-3 pt-2 text-xs text-muted-foreground">
        {reading.model_id} · attempt {reading.attempt} · {humanizeEnum(reading.status)}
      </p>
      {reading.output ? (
        <RowsTable rows={extractionRows(reading.output)} provenance={null} />
      ) : (
        <p className="p-3 text-sm text-muted-foreground">
          {reading.status === "OK" ? "The output was removed." : `${name} did not return a result.`}
        </p>
      )}
    </div>
  );
}

function DisagreementsPane({ items }: { items: Extraction["disagreements"] }) {
  if (items.length === 0) {
    return <p className="p-3 text-sm text-muted-foreground">The readers agreed on every value.</p>;
  }
  return (
    <Table className="text-[13px]">
      <TableHeader>
        <TableRow>
          <TableHead className="h-8 text-xs">Field</TableHead>
          <TableHead className="h-8 text-xs">Reader A</TableHead>
          <TableHead className="h-8 text-xs">Reader B</TableHead>
          <TableHead className="h-8 text-xs">Chosen</TableHead>
          <TableHead className="h-8 text-xs">Reason</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((d) => (
          <TableRow key={d.field_path}>
            <TableCell className="font-mono">{d.field_path}</TableCell>
            <TableCell className="font-mono whitespace-normal break-all">{d.value_a ?? "—"}</TableCell>
            <TableCell className="font-mono whitespace-normal break-all">{d.value_b ?? "—"}</TableCell>
            <TableCell>
              <Pill tone={sourceTone(d.chosen)} mono>
                {SOURCE_TAG[d.chosen] ?? d.chosen}
              </Pill>
            </TableCell>
            <TableCell className="whitespace-normal">{d.reason}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Final, Reader A, Reader B and Disagreements for one item's extraction. */
export function ExtractionTabs({ extraction }: { extraction: Extraction }) {
  const finalRows = extraction.final ? extractionRows(extraction.final) : null;
  return (
    <GlassPanel as="div" className="min-w-0 overflow-x-auto">
    <Tabs defaultValue="final" className="min-w-0">
      <div className="flex items-center justify-between gap-2 px-2 pt-2">
        <TabsList>
          <TabsTrigger value="final">Final</TabsTrigger>
          <TabsTrigger value="reader_a">Reader A</TabsTrigger>
          <TabsTrigger value="reader_b">Reader B</TabsTrigger>
          <TabsTrigger value="disagreements">
            Disagreements{extraction.disagreements.length > 0 ? ` (${extraction.disagreements.length})` : ""}
          </TabsTrigger>
        </TabsList>
        {extraction.confidence !== null ? (
          <span className="text-xs text-muted-foreground">
            Overall {Math.round(extraction.confidence * 100)}%
          </span>
        ) : null}
      </div>
      <TabsContent value="final">
        {extraction.missing_reader ? (
          <p className="px-3 pt-2 text-xs text-warn-ink">
            Reader {extraction.missing_reader} returned nothing; this is the other reader&apos;s result.
          </p>
        ) : null}
        {finalRows ? (
          <RowsTable rows={finalRows} provenance={extraction.provenance} />
        ) : (
          <p className="p-3 text-sm text-muted-foreground">
            {extraction.purged
              ? "The extraction was removed under the retention policy."
              : "No extraction yet."}
          </p>
        )}
      </TabsContent>
      <TabsContent value="reader_a">
        <ReaderPane reading={extraction.reader_a} name="Reader A" />
      </TabsContent>
      <TabsContent value="reader_b">
        <ReaderPane reading={extraction.reader_b} name="Reader B" />
      </TabsContent>
      <TabsContent value="disagreements">
        <DisagreementsPane items={extraction.disagreements} />
      </TabsContent>
    </Tabs>
    </GlassPanel>
  );
}
