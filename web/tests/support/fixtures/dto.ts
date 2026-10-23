import type { Schemas } from "@/lib/api/types";

/** Typed builders for the flow and item DTOs. Reused by the s19, s20, s21 and s41 tests. */

export type DeepPartial<T> = T extends readonly (infer U)[]
  ? readonly U[] | DeepPartial<U>[]
  : T extends object
    ? { [K in keyof T]?: DeepPartial<T[K]> }
    : T;

const NOW = "2026-10-23T12:00:00+00:00";

const TILE_ORDER: Schemas["FlowTile"][] = [
  "INTAKE",
  "CLASSIFY",
  "EXTRACT",
  "ADJUDICATE",
  "VALIDATE",
  "RESOLVE_CUSTOMER",
  "FAST_PATH",
  "MATCH_RECEIPT",
  "AWAITING_RECEIPT",
  "MATCH_LINES",
  "APPLY",
  "WRITE_BACK",
  "DONE",
];

export function buildTile(
  stage: Schemas["FlowTile"],
  overrides: Partial<Schemas["FlowTileOut"]> = {},
): Schemas["FlowTileOut"] {
  return {
    stage,
    in_queue: 0,
    in_progress: 0,
    errors: 0,
    throughput_per_min: Array.from({ length: 60 }, () => 0),
    p95_dwell_s: null,
    awaiting_buckets:
      stage === "AWAITING_RECEIPT" ? { "0-2d": 0, "3-7d": 0, "8-30d": 0, ">30d": 0 } : null,
    ...overrides,
  };
}

export function buildFlowSummary(
  overrides: DeepPartial<Schemas["FlowSummaryOut"]> = {},
): Schemas["FlowSummaryOut"] {
  const base: Schemas["FlowSummaryOut"] = {
    kpis: {
      in_today: 412,
      auto_applied_pct: 78.4,
      applied_by_currency: [{ currency: "USD", amount: "1284930.17" }],
      needs_person: 37,
    },
    stages: TILE_ORDER.map((stage) => buildTile(stage)),
    pollers: [
      { name: "intake-poller", last_cycle_at: NOW },
      { name: "receipt-watcher", last_cycle_at: NOW },
    ],
    cohere_utilisation_pct: null,
    backlog: [],
    generated_at: NOW,
  };
  return {
    ...base,
    ...(overrides as Partial<Schemas["FlowSummaryOut"]>),
    kpis: { ...base.kpis, ...(overrides.kpis as Partial<Schemas["FlowKpisOut"]> | undefined) },
  };
}

export function buildLock(overrides: Partial<Schemas["LockInfoOut"]> = {}): Schemas["LockInfoOut"] {
  return {
    item_id: 20481,
    owner: "ana@example.test",
    owner_name: "Ana Reyes",
    acquired_at: "2026-10-23T11:30:00+00:00",
    expires_at: "2026-10-23T12:30:00+00:00",
    ...overrides,
  };
}

export function buildStageItem(overrides: Partial<Schemas["StageItemOut"]> = {}): Schemas["StageItemOut"] {
  return {
    id: 20481,
    payer_name: "Northwind Traders",
    amount: "12480.00",
    currency: "USD",
    received_at: "2026-10-23T09:00:00+00:00",
    attempts: 1,
    stage: "MATCH_RECEIPT",
    state: "PENDING",
    payment_status: null,
    lock: null,
    ...overrides,
  };
}

export function buildStageItems(
  n: number,
  overrides: Partial<Schemas["StageItemOut"]> = {},
): Schemas["StageItemsOut"] {
  return {
    items: Array.from({ length: n }, (_, index) =>
      buildStageItem({ id: 20481 + index, ...overrides }),
    ),
    total: n,
    page: 1,
    page_size: 50,
  };
}

type Extracted<V> = { value: V | null; source: Schemas["SourceLocation"] | null; confidence: number };

function extracted<V>(
  value: V,
  confidence: number,
  source: Schemas["SourceLocation"] | null = null,
): Extracted<V> {
  return { value, source, confidence };
}

function box(x: number, y: number, w: number, h: number, quote: string): Schemas["SourceLocation"] {
  return { part_no: 1, page: 1, bbox: { x, y, w, h }, quote };
}

function buildExtraction(): Schemas["RemittanceExtraction"] {
  return {
    payer_name: extracted("Northwind Traders", 0.97, box(0.1, 0.1, 0.3, 0.04, "Northwind Traders")),
    payer_bank_account: extracted("DE00 0000 0000", 0.8),
    remittance_reference: extracted("REM-2291", 0.9, box(0.1, 0.18, 0.2, 0.03, "REM-2291")),
    payment_amount: extracted("12480.00", 0.95, box(0.6, 0.7, 0.25, 0.04, "12,480.00")),
    currency_raw: extracted("USD", 0.9),
    currency: extracted("USD", 0.9),
    currency_ambiguous: false,
    dates: [],
    payment_date: extracted("2026-10-22", 0.92, box(0.6, 0.1, 0.2, 0.03, "22 Oct 2026")),
    lines: [
      {
        line_no: 1,
        kind: "INVOICE",
        transaction_number: "INV-1001",
        amount_paid: "10000.00",
        confidence: 0.9,
        source: box(0.1, 0.4, 0.8, 0.03, "INV-1001 10,000.00"),
      },
      {
        line_no: 2,
        kind: "INVOICE",
        transaction_number: "INV-1002-1",
        amount_paid: "2480.00",
        confidence: 0.85,
        source: box(0.1, 0.45, 0.8, 0.03, "INV-1002-1 2,480.00"),
      },
    ],
    po_refs: [],
    sales_order_refs: [],
    ers_refs: [],
    bank_fees: [],
    notes: null,
  } as unknown as Schemas["RemittanceExtraction"];
}

export function buildItemDetail(
  overrides: DeepPartial<Schemas["ItemDetailOut"]> = {},
): Schemas["ItemDetailOut"] {
  const final = buildExtraction();
  const base: Schemas["ItemDetailOut"] = {
    item: {
      id: 20481,
      stage: "MATCH_LINES",
      state: "PENDING",
      payment_status: null,
      payer_name: "Northwind Traders",
      amount: "12480.00",
      currency: "USD",
      payment_date: "2026-10-22",
      customer_account_number: "1001",
      received_at: "2026-10-23T09:00:00+00:00",
      updated_at: "2026-10-23T11:00:00+00:00",
      attempts: 1,
      last_error_code: null,
      escalation_summary: null,
      info_flags: [],
      version: 3,
    },
    lock: null,
    extraction: {
      final,
      provenance: {
        payer_name: "both",
        remittance_reference: "A",
        payment_amount: "B",
        payment_date: "both",
        "lines[0]": "A",
        "lines[1]": "both",
      },
      disagreements: [
        {
          field_path: "payment_amount",
          value_a: "12480.00",
          value_b: "12,480.00",
          chosen: "B",
          reason: "Same amount; B kept the printed form.",
        },
      ],
      confidence: 0.91,
      reader_a: { status: "OK", model_id: "claude-opus-5-5", attempt: 1, output: final, created_at: NOW },
      reader_b: { status: "OK", model_id: "cohere.command-a-vision", attempt: 1, output: final, created_at: NOW },
      missing_reader: null,
      purged: false,
    },
    parts: [{ part_no: 1, kind: "PDF", media_type: "application/pdf", purged: false }],
    lines: [
      {
        line_no: 1,
        transaction_number: "INV-1001",
        stated_amount: "10000.00",
        fusion_balance: "10000.00",
        applied_amount: "10000.00",
        line_status: "allocation-applied",
        fusion_result_code: null,
      },
      {
        line_no: 2,
        transaction_number: "INV-1002-1",
        stated_amount: "2480.00",
        fusion_balance: "2500.00",
        applied_amount: "2480.00",
        line_status: "allocation-applied-short-pay",
        fusion_result_code: null,
      },
    ],
    resolution: {
      anchor_customer_number: "1001",
      related_customer_numbers: [],
      method: "invoice",
      currency: "USD",
      flags: [],
    },
    receipt: {
      receipt_id: 7001,
      receipt_number: "RCPT-7001",
      decided_by: "system",
      score: 0.98,
      reservation_status: "ACTIVE",
    },
  };
  const patch = overrides as Partial<Schemas["ItemDetailOut"]>;
  return {
    ...base,
    ...patch,
    item: { ...base.item, ...(overrides.item as Partial<Schemas["ItemOut"]> | undefined) },
    extraction: {
      ...base.extraction,
      ...(overrides.extraction as Partial<Schemas["ExtractionOut"]> | undefined),
    },
  };
}

export function buildHistoryRow(
  overrides: Partial<Schemas["HistoryRowOut"]> = {},
): Schemas["HistoryRowOut"] {
  return {
    id: 1,
    at: "2026-10-23T09:00:05+00:00",
    action: "STAGE_TRANSITION",
    actor_kind: "SYSTEM",
    actor_id: "system",
    actor_name: "CashApp automation",
    from_stage: "INTAKE",
    to_stage: "CLASSIFY",
    from_state: "PENDING",
    to_state: "PENDING",
    error_code: null,
    reasoning: null,
    payload: { note: "advanced" },
    purged: false,
    ...overrides,
  };
}

export function buildHistory(n: number): Schemas["HistoryOut"] {
  return {
    items: Array.from({ length: n }, (_, index) =>
      buildHistoryRow({ id: index + 1, at: `2026-10-23T09:00:${String(index % 60).padStart(2, "0")}+00:00` }),
    ),
    total: n,
  };
}

export function buildItemChanged(
  overrides: Partial<Schemas["ItemChangedOut"]> = {},
): Schemas["ItemChangedOut"] {
  return {
    id: 20481,
    stage: "MATCH_RECEIPT",
    state: "PENDING",
    lock: null,
    payment_status: null,
    updated_at: "2026-10-23T12:00:05+00:00",
    ...overrides,
  };
}

const ROLE_PERMISSIONS: Record<
  "ADMIN" | "OPERATOR" | "REVERSER" | "VIEWER",
  Schemas["Permission"][]
> = {
  ADMIN: [
    "items:read",
    "items:work",
    "apply:reverse",
    "classification:override",
    "config:read",
    "config:write",
    "reports:read",
    "backlog:run",
    "chat:use",
  ],
  OPERATOR: ["items:read", "items:work", "classification:override", "reports:read", "chat:use", "config:read"],
  REVERSER: ["apply:reverse"],
  VIEWER: ["items:read", "reports:read", "config:read"],
};

/** Permissions come from the roles, mirroring the API's role table (for tests only). */
export function buildMe(roles: ("ADMIN" | "OPERATOR" | "REVERSER" | "VIEWER")[] = ["ADMIN"]): Schemas["MeResponse"] {
  const permissions = [...new Set(roles.flatMap((role) => ROLE_PERMISSIONS[role]))];
  return {
    subject: "test-user",
    display_name: "Test User",
    email: "test.user@example.test",
    groups: [],
    roles,
    permissions,
  };
}
