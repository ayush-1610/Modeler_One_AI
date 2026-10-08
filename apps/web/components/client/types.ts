// P3 client data. The answers are the API's generated response models (lib/api-types.ts); what they carry as open
// objects (a stored client file, a dissolution profile, the reading form) is typed here.

import type { Narrow, Schema } from "@/lib/api";

export type Triage = { sheet: string; category: string; evidence_cell: string; evidence_quote: string; by: string; note: string };
export type IssueRow = { code: string; location: string; message: string };
export type KeptRow = { row: number; values: Record<string, unknown>; cells: Record<string, string> };
export type Mapping = { recipe: { recipe_id: string; tables?: { sheet: string; record_type: string }[] }; datasets: string[];
                        dissolution_records?: number; replaced_by?: string };
export type ClientFile = {
  id: string; file: string; sha256: string; kind: string; template: boolean; triage: Triage[]; datasets: string[];
  evidence: string[]; dissolution: KeptRow[]; products: KeptRow[]; urine_feces: KeptRow[]; issues: IssueRow[];
  brief_mismatches: string[]; other_sheets: string[]; mappings?: Mapping[];
};
export type Reconciled = Schema<"ReconciledRow">;
export type Fit = { t50_min: number | null; shape: number | null; lag_min: number; se_t50: number | null; se_shape: number | null;
                    rmse_percent: number | null; n_points: number; converged: boolean; note: string; engine_confirmed: boolean };
export type Profile = { id: string; label: string; key: Record<string, unknown>; times_min: number[]; mean: number[];
                        cv: (number | null)[]; n: number; flags: string[]; release_model: "Weibull" | "Dissolved" | "Table";
                        fit: Fit | null; files: string[] };
export type Comparison = { test: string; reference: string; condition: string; f2: number | null; similar: boolean | null;
                           applicable: boolean; reasons: string[]; times_used: number[]; ruleset: string };
// GET /projects/{id}/client-data (ClientDataPage), with the stored files and profiles typed
export type View = Narrow<Schema<"ClientDataPage">, {
  files: ClientFile[];
  dissolution: Narrow<Schema<"Dissolution">, { profiles: Profile[]; comparisons: Comparison[] }>;
}>;

/** The reading form of one sheet (modeler_intake.sheet_form.SheetForm). */
export type SheetForm = {
  sheet: string;
  kind: "concentration_time" | "dissolution";
  layout: "times_down" | "times_across";
  header_row: number;
  first_data_row: number;
  last_data_row: number | null;
  time_column: string | null;
  subject_column: string | null;
  group_column: string | null;
  value_columns: string[];
  sd_column: string | null;
  n_column: string | null;
  time_unit: string;
  value_unit: string;
  statistic: "individual" | "arithmetic_mean" | "geometric_mean" | "median";
  lloq: number | null;
  decimal_comma: boolean;
  below_lloq_tokens: string[];
  missing_tokens: string[];
  constants: Record<string, string>;
  evidence: { cell: string; quote: string; supports: string; field: string; value: string }[];
  study: Record<string, string>;
  mean_column: string | null;
  mean_row: number | null;
  mean_statistic: "arithmetic_mean" | "geometric_mean" | "median";
  mean_sd_column: string | null;
  mean_n: number | null;
};

// GET .../sheets/{sheet} (SheetView), with the reading form typed
export type SheetView = Narrow<Schema<"SheetView">, { form: SheetForm }>;

// POST .../{sid}:map: a preview (MapPreview), or a confirmed reading that also names the datasets it proposed
export type ReadPreview = Schema<"MapPreview"> & { datasets?: string[] };

/** Sheet kinds a reading turns into data (the others are kept as they are). */
export const DATA_SHEETS = new Set(["PK_INDIVIDUAL", "PK_SUMMARY", "DISSOLUTION", "URINE_FECES"]);

export const CATEGORY_LABEL: Record<string, string> = {
  PK_INDIVIDUAL: "PK, individual", PK_SUMMARY: "PK, mean", PK_PARAMETERS: "PK parameters", DISSOLUTION: "dissolution",
  PRODUCT_INFO: "product info", STUDIES: "study list", DEMOGRAPHICS: "demographics", BIOANALYTICAL: "bioanalytical",
  PHYSCHEM_INVITRO: "physchem / in vitro", URINE_FECES: "urine / feces", OTHER: "not sorted",
};

/** Sheets read by a confirmed recipe, with the datasets each reading made. */
export function readSheets(file: ClientFile): Map<string, number> {
  const out = new Map<string, number>();
  for (const m of (file.mappings ?? []).filter((x) => !x.replaced_by)) {
    for (const t of m.recipe.tables ?? []) {
      out.set(t.sheet, (out.get(t.sheet) ?? 0) + Math.max(m.datasets.length, m.dissolution_records ? 1 : 0));
    }
  }
  return out;
}
