import type { ArtifactHighlight } from "@/components/common/artifact-viewer";
import type { Schemas } from "@/lib/api/types";

type Extraction = Schemas["RemittanceExtraction"];
type Source = Schemas["SourceLocation"];

/** One displayable value of an extraction, addressed by the same path the provenance uses. */
export type ExtractionRow = {
  path: string;
  label: string;
  value: string;
  source: Source | null;
  confidence: number;
};

type FieldLike = { value?: string | null; source?: Source | null; confidence: number };

const DASH = "—";

function field(path: string, label: string, extracted: FieldLike, suffix?: string | null): ExtractionRow {
  const value = extracted.value ?? null;
  return {
    path,
    label,
    value: value === null ? DASH : suffix ? `${value} ${suffix}` : value,
    source: extracted.source ?? null,
    confidence: extracted.confidence,
  };
}

/** Header fields, every candidate date and every line, in display order. */
export function extractionRows(extraction: Extraction): ExtractionRow[] {
  const rows: ExtractionRow[] = [
    field("payer_name", "Payer", extraction.payer_name),
    field("payer_bank_account", "Payer bank account", extraction.payer_bank_account),
    field("remittance_reference", "Remittance reference", extraction.remittance_reference),
    field(
      "payment_amount",
      "Payment amount",
      extraction.payment_amount,
      extraction.currency.value ?? null,
    ),
    field("currency", "Currency", extraction.currency),
    field("payment_date", "Payment date", extraction.payment_date),
  ];
  extraction.dates.forEach((candidate, index) => {
    rows.push({
      path: `dates[${index}]`,
      label: `Date (${candidate.kind})`,
      value: candidate.value,
      source: candidate.source ?? null,
      confidence: candidate.confidence,
    });
  });
  extraction.lines.forEach((line, index) => {
    const amount = line.amount_paid ? ` · ${line.amount_paid}` : "";
    rows.push({
      path: `lines[${index}]`,
      label: `Line ${line.line_no}`,
      value: `${line.transaction_number || DASH}${amount}`,
      source: line.source ?? null,
      confidence: line.confidence,
    });
  });
  return rows;
}

/** One highlight per value whose source has a box or a quote; the id is the field path. */
export function highlightsFor(extraction: Extraction | null): ArtifactHighlight[] {
  if (!extraction) return [];
  const highlights: ArtifactHighlight[] = [];
  for (const row of extractionRows(extraction)) {
    const source = row.source;
    if (!source || (!source.bbox && !source.quote)) continue;
    highlights.push({
      id: row.path,
      label: row.label,
      partNo: source.part_no,
      page: source.page ?? null,
      bbox: source.bbox ?? null,
      quote: source.quote ?? null,
    });
  }
  return highlights;
}
