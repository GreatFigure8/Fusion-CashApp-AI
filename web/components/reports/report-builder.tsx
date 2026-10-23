"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { ActionButton } from "@/components/common/action-button";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  filenameFromDisposition,
  KIND_LABELS,
  SECTION_LABELS,
  WINDOW_LABELS,
} from "@/lib/reports/html";
import {
  DEFAULT_SECTIONS,
  HTML_SECTIONS,
  htmlReportKind,
  htmlWindow,
  type HtmlReportParams,
  type HtmlSection,
  type ReportExportOut,
} from "@/lib/reports/schemas";

import { RecentExports } from "./recent-exports";
import { ReportPreview, type PreviewReport } from "./report-preview";

function saveBlob(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
}

/** The form column, the live preview and the export log. The only client state is the form. */
export function ReportBuilder({
  initial,
  recent,
  now,
}: {
  initial: HtmlReportParams;
  recent: readonly ReportExportOut[];
  now: string;
}): React.JSX.Element {
  const router = useRouter();
  const [params, setParams] = React.useState<HtmlReportParams>(initial);
  const [hasData, setHasData] = React.useState<boolean | null>(null);
  const [exporting, setExporting] = React.useState(false);
  const [exportFailed, setExportFailed] = React.useState(false);

  const change = (next: (p: HtmlReportParams) => HtmlReportParams): void => {
    setExportFailed(false);
    setParams(next);
  };

  const onReport =React.useCallback((report: PreviewReport) => setHasData(report.hasData), []);

  const toggle = (section: HtmlSection, on: boolean): void => {
    change((p) => {
      const picked = HTML_SECTIONS.filter((s) => (s === section ? on : p.sections.includes(s)));
      return { ...p, sections: picked };
    });
  };

  const runExport = async (): Promise<void> => {
    setExporting(true);
    setExportFailed(false);
    try {
      const response = await fetch("/api/reports/html/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      if (!response.ok) {
        setExportFailed(true);
        return;
      }
      const filename =
        filenameFromDisposition(response.headers.get("Content-Disposition")) ?? "report.html";
      saveBlob(await response.blob(), filename);
      router.refresh();
    } catch {
      setExportFailed(true);
    } finally {
      setExporting(false);
    }
  };

  const canExport = params.sections.length > 0 && !exporting && hasData === true;

  return (
    <div className="flex flex-wrap items-start gap-4">
      <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-4">
        <GlassPanel>
          <PanelHeader title="Build a report" />
          <PanelBody className="flex flex-col gap-3.5">
            <div className="flex flex-col gap-1.5">
              <MonoLabel as="p">Report</MonoLabel>
              <Select
                value={params.kind}
                onValueChange={(value) => {
                  const kind = htmlReportKind.safeParse(value);
                  if (kind.success) {
                    change((p) => ({
                      ...p,
                      kind: kind.data,
                      sections: [...DEFAULT_SECTIONS[kind.data]],
                    }));
                  }
                }}
              >
                <SelectTrigger aria-label="Report" className="w-full">
                  <SelectValue>{KIND_LABELS[params.kind]}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {htmlReportKind.options.map((kind) => (
                    <SelectItem key={kind} value={kind}>
                      {KIND_LABELS[kind]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <MonoLabel as="p">Window</MonoLabel>
              <Select
                value={params.window}
                onValueChange={(value) => {
                  const window = htmlWindow.safeParse(value);
                  if (window.success) change((p) => ({ ...p, window: window.data }));
                }}
              >
                <SelectTrigger aria-label="Window" className="w-full">
                  <SelectValue>{WINDOW_LABELS[params.window]}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {htmlWindow.options.map((window) => (
                    <SelectItem key={window} value={window}>
                      {WINDOW_LABELS[window]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <MonoLabel as="p">Sections</MonoLabel>
            {HTML_SECTIONS.map((section) => (
              <Label key={section} className="min-h-8 gap-2.5 text-sm font-normal">
                <Checkbox
                  checked={params.sections.includes(section)}
                  onCheckedChange={(checked) => toggle(section, checked === true)}
                  className="size-4"
                />
                {SECTION_LABELS[section]}
              </Label>
            ))}
            <ActionButton glow disabled={!canExport} onClick={() => void runExport()}>
              Export HTML
            </ActionButton>
            <span className="text-[12.5px] text-muted-foreground">
              A single self-contained file with inline styles and no scripts. Safe to email.
            </span>
          </PanelBody>
        </GlassPanel>
        <RecentExports exports={recent} now={new Date(now)} />
      </div>
      <div className="min-w-0 flex-[999_1_560px]">
        {exportFailed ? (
          <StateCard
            kind="error"
            label="Error · export"
            headline="The export didn't finish"
            body="The report query timed out. No file was created."
            actions={
              <Button variant="outline" onClick={() => void runExport()}>
                Try again
              </Button>
            }
          />
        ) : (
          <ReportPreview params={params} onReport={onReport} />
        )}
      </div>
    </div>
  );
}
