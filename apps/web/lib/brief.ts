// The Project Brief (plan §6): field records with status, citations and confidence; the schema it is rendered from.

export type FieldStatus =
  | "ENTERED" | "EXTRACTED" | "RETRIEVED" | "COMPUTED" | "EDITED" | "CONFIRMED" | "MISSING" | "NOT_APPLICABLE";

export type Citation = { doc_sha256: string; page: number; quote: string; locator: string; source: string };

export type FieldRecord = {
  value: unknown;
  unit: string | null;
  status: FieldStatus;
  citations: Citation[];
  confidence: "A" | "B" | "C" | "D" | null;
  note: string;
  by: string | null;
  at: string | null;
};

export type FieldDef = {
  id: string;
  section: string;
  label: string;
  kind: "text" | "number" | "enum" | "list" | "bool" | "multi";
  required: boolean;
  options: string[];
  unit: string | null;
  help: string;
};

export type GroupDef = { id: string; section: string; label: string; required: boolean; fields: FieldDef[] };

export type Question = {
  id: string;
  field: string;
  question: string;
  answer: string;
  status: "open" | "answered" | "accepted_as_limitation";
  raised_by: string;
};

export type Brief = {
  schema: string;
  drug_name: string;
  fields: Record<string, FieldRecord>;
  groups: Record<string, Record<string, FieldRecord>[]>;
  questions: Question[];
};

export type BriefIssue = { code: string; path: string; message: string };

export type BriefView = {
  artifact: { version: number; status: string; sha256: string; reason: string; created_by: string; created_at: string;
              stale_reasons: string[]; approvals: { by: string; printed_name: string; meaning: string; at: string }[] };
  brief: Brief;
  issues: BriefIssue[];
  blocking: number;
  summary: { by_status: Record<string, number>; groups: Record<string, number>; open_questions: number };
  catalog: { schema: string; sections: Record<string, string>; fields: FieldDef[]; groups: GroupDef[] };
  agents: { enabled: boolean; provider?: string; model?: string; problem?: string };
  extraction_running: boolean;
  runs: { run_id: string; agent: string; status: string; provider: string; model: string; started_at: string;
          finished_at: string | null; summary: Record<string, unknown> }[];
};

export type DocumentView = {
  id: string;
  sha256: string;
  name: string;
  kind: string;
  role: string;
  n_pages: number;
  size_bytes: number;
  warnings: string[];
  uploaded_at: string;
  uploaded_by: string;
};

export type Impact = {
  unchanged: boolean;
  changes: { path: string; before: unknown; after: unknown; kind: string }[];
  affected: { ref: { kind: string; id: string; version: number }; status: string; effect: string; needs_signature: boolean }[];
  notes: string[];
};

export const EMPTY_RECORD: FieldRecord = {
  value: null, unit: null, status: "MISSING", citations: [], confidence: null, note: "", by: null, at: null,
};

export function display(record: FieldRecord): string {
  const v = record.value;
  if (v === null || v === undefined || v === "") return "";
  if (Array.isArray(v)) return v.join("; ");
  if (typeof v === "boolean") return v ? "yes" : "no";
  return `${String(v)}${record.unit ? ` ${record.unit}` : ""}`;
}

export const STATUS_CHIP: Record<FieldStatus, string> = {
  ENTERED: "brand", EXTRACTED: "brand", RETRIEVED: "brand", COMPUTED: "brand", EDITED: "medium", CONFIRMED: "low",
  MISSING: "high", NOT_APPLICABLE: "neutral",
};
