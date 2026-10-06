// P3 client data: the shapes the client-data endpoints return (services/api/src/modeler_api/client_api.py).

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
export type Reconciled = { req_id: string; label: string; criticality: string; applies: string; status: string;
                           delivered: string[]; detail: string; cross_check: boolean; literature_accepted: string[];
                           kind: string; target: string; product: string | null };
export type Fit = { t50_min: number | null; shape: number | null; lag_min: number; se_t50: number | null; se_shape: number | null;
                    rmse_percent: number | null; n_points: number; converged: boolean; note: string; engine_confirmed: boolean };
export type Profile = { id: string; label: string; key: Record<string, unknown>; times_min: number[]; mean: number[];
                        cv: (number | null)[]; n: number; flags: string[]; release_model: "Weibull" | "Dissolved" | "Table";
                        fit: Fit | null; files: string[] };
export type Comparison = { test: string; reference: string; condition: string; f2: number | null; similar: boolean | null;
                           applicable: boolean; reasons: string[]; times_used: number[]; ruleset: string };
export type View = {
  template: string;
  data_plan: { version: number; status: string };
  dissolution: { profiles: Profile[]; comparisons: Comparison[]; problems: string[] };
  files: ClientFile[];
  reconciliation: { rows: Reconciled[]; unpromised: string[]; blocking: string[] };
  register: { status: string; approvals: { printed_name: string; at: string }[] } | null;
  agents: { enabled: boolean };
  running: boolean;
};

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
};

export type SheetView = {
  sheet: string; rows: string[][]; max_row: number; max_column: number; category: string; form: SheetForm; notes: string[];
  products: { name: string; role: string }[]; read_before: { recipe_id: string; datasets: string[] }[];
};

export type ReadPreview = {
  ready: boolean; issues: IssueRow[]; questions: string[]; concentrations: number; dissolution: number; studies: string[];
  recipe: unknown;
  sample: { series: string[]; times: number[]; time_unit?: string; unit?: string; below_lloq: number; values_hidden: boolean;
            rows: { series: string; time: number; value: number | null; blq?: boolean; cell: string }[] };
  datasets?: string[];
};

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
