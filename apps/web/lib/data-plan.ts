// The P1 data plan (plan §7): the requirement matrix and the feasibility report are stored content the API sends as open
// objects (`RequirementsPage`); they are typed here once, for the Start checklist.

import type { Narrow, Schema } from "./api";

export type Item = {
  req_id: string;
  label: string;
  kind: string;
  target: string;
  group: string;
  template: string;
  pksim: Record<string, string> | null;
  pksim_status: "HARVESTED" | "TO_HARVEST" | "NOT_APPLICABLE";
  unit: string | null;
  criticality: "REQUIRED" | "CONDITIONAL" | "OPTIONAL";
  applies: "yes" | "no" | "undetermined";
  condition_text: string;
  needed_for: string[];
  data_category: string;
  provider: string;
  provider_source: string;
  provider_statement: string;
  purpose: string | null;
  due_date: string | null;
  cross_check: boolean;
  conditions: string[];
  plausibility: string;
  product: string | null;
  note: string;
  status: string;
};

export type FeasibilityLine = { feature: string; needed_because: string; status: string; route: string };

// GET /projects/{id}/requirements (RequirementsPage); the stored matrix and feasibility report are typed here
export type PlanView = Narrow<Schema<"RequirementsPage">, {
  matrix: { templates: string[]; items: Item[]; overrides: { req_id: string; reason: string; by: string }[]; notes: string[] };
  feasibility: { lines: FeasibilityLine[]; blocking?: number; undetermined?: number; status: string | null };
}>;
