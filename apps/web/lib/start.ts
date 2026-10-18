// Step 1 · Start (docs/plans/2026-10-19-p0-p5-redesign.md §3.1): the page's answer and how a brief record reads.
// Every shape is the API's generated response model (lib/api-types.ts); the rules (what Start needs, the scope gates,
// the ICH M15 bounds) are the API's (`modeler_project.start`), never repeated here.

import type { Schema } from "./api";

export type StartPage = Schema<"StartPage">;
export type StartField = Schema<"StartField">;
export type FieldRecord = Schema<"FieldRecordView">;
export type Citation = Schema<"CitationView">;
export type Gate = Schema<"GateView">;
export type ChecklistItem = Schema<"ChecklistItemView">;
export type NoteGroup = Schema<"NoteGroup">;
export type FieldChange = Schema<"FieldChange">;

/** Where a value came from, in words. */
export const SOURCE_LABEL: Record<string, string> = {
  ENTERED: "entered", EXTRACTED: "from the documents", RETRIEVED: "from PubChem", COMPUTED: "computed",
  EDITED: "edited", CONFIRMED: "confirmed", MISSING: "not stated", NOT_APPLICABLE: "not applicable",
};

export const SOURCE_CHIP: Record<string, string> = {
  ENTERED: "brand", EXTRACTED: "brand", RETRIEVED: "brand", COMPUTED: "brand", EDITED: "medium", CONFIRMED: "low",
  MISSING: "neutral", NOT_APPLICABLE: "neutral",
};

/** A field holds a value a person or a source gave (not missing, not "not applicable"). */
export function filled(field: StartField): boolean {
  const { status, value } = field.record;
  return status !== "MISSING" && status !== "NOT_APPLICABLE" && value !== null && value !== "" &&
    !(Array.isArray(value) && value.length === 0);
}

/** A field's value as the page shows it: option labels for choices, the unit for a number. */
export function shown(field: StartField): string {
  if (!filled(field)) return "";
  const { value, unit } = field.record;
  const label = (v: unknown) => field.options.find((o) => o.value === v)?.label ?? String(v);
  if (Array.isArray(value)) return value.map(label).join("; ");
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (field.options.length) return label(value);
  return unit ? `${String(value)} ${unit}` : String(value);
}

export const PROVIDER_LABEL: Record<string, string> = {
  CLIENT: "client", LITERATURE: "literature", SPONSOR_TO_MEASURE: "sponsor to measure", PREDICT: "predicted",
  STRUCTURE: "from the structure", LIBRARY: "PK-Sim library", STUDY: "from a study", PROPOSAL: "the proposal",
  NOT_NEEDED: "not needed", NOT_STATED: "not stated",
};
// What a person may say provides an item (the data plan's override, `requirements_api.OverrideRequest`)
export const PROVIDERS = ["CLIENT", "LITERATURE", "SPONSOR_TO_MEASURE", "PREDICT", "STRUCTURE", "LIBRARY", "STUDY",
  "PROPOSAL", "NOT_NEEDED"] as const satisfies NonNullable<Schema<"OverrideRequest">["provider"]>[];

/** What arrived for a checklist item, in words (a client item's reconciliation, else the item's own state). */
export const ITEM_STATUS: Record<string, { label: string; chip: string }> = {
  DELIVERED: { label: "arrived", chip: "low" }, PARTIAL: { label: "in part", chip: "medium" },
  MISSING: { label: "not yet", chip: "neutral" }, NOT_AVAILABLE: { label: "not available", chip: "high" },
  WAIVED: { label: "waived", chip: "neutral" }, SATISFIED: { label: "covered", chip: "low" }, OPEN: { label: "open", chip: "neutral" },
};
