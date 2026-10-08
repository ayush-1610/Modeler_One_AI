// The Project Brief (plan §6): field records with status, citations and confidence; the schema it is rendered from.
// The page's answers are the API's generated response models; the brief itself is stored content, typed here.

import type { Schema } from "./api";

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

// `GET /projects/{id}/brief` (BriefPage); the brief and its catalog's field kinds are narrowed to the stored schema
export type BriefView = Omit<Schema<"BriefPage">, "brief" | "catalog"> & {
  brief: Brief;
  catalog: Omit<Schema<"BriefCatalog">, "fields" | "groups"> & { fields: FieldDef[]; groups: GroupDef[] };
};

export type DocumentView = Schema<"DocumentView">;

export type Impact = Schema<"ImpactView">;

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
