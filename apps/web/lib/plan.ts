// P5 · model plan (plan §11, review layer L3): the types of the plan API and the calls the canvas makes.
// The ModelPlan JSON is the record; the canvas only renders it and sends changes, each with a reason.

import type { Envelope } from "@/lib/api";
import { apiGet, apiSend } from "@/lib/writes";

export type Role = "S1" | "S2" | "S3" | "S5" | "S6" | "SUPPORTIVE";
export const ROLES: Role[] = ["S1", "S2", "S3", "S5", "S6", "SUPPORTIVE"];
export const ROLE_LABEL: Record<Role, string> = {
  S1: "S1 · IV disposition", S2: "S2 · oral absorption", S3: "S3 · formulation / fed",
  S5: "S5 · external validation", S6: "S6 · application", SUPPORTIVE: "supportive",
};

export type Placement = { role: Role; by: string; userLocked: boolean; reason: string; at: string | null };
export type FitChoice = { stages: string[]; lower: number; upper: number; scale: "linear" | "log"; by: string;
                          userLocked: boolean; reason: string };
export type Proposal = { id: string; kind: "role" | "fit"; target: string; value: Record<string, unknown>; reason: string;
                         by: string; status: "PENDING" | "ACCEPTED" | "REJECTED"; decided_by: string | null; decision_reason: string };
export type Structure = {
  objective: string; context_of_use: string; model_risk: "low" | "medium" | "high"; food_effect_in_question: boolean;
  measured_fed_solubility: boolean; planned_applications: string[]; locked: string[]; reasons: Record<string, string>;
};
export type StudyView = {
  study_id: string; study_class: string; score: number; route: string; dose_mg: number; formulation: string;
  food_state: string; design: string; n: number; origin: string; evaluable: boolean; kind: string; purpose: string;
  default_role: Role; new: boolean;
};
export type ModelPlan = {
  schema: string; compound: string; studies: StudyView[]; placements: Record<string, Placement>;
  fits: Record<string, FitChoice>; structure: Structure; default_rationale: string[]; default_limitations: string[];
  rationale: Record<string, string>; proposals: Proposal[]; acknowledged: Record<string, string>;
  layout: Record<string, { x: number; y: number }>; fit_candidates: Record<string, string[]>; budgets: Record<string, number>;
};
export type Violation = { id: string; severity: "error" | "warning"; rule: string; target: string; message: string;
                          acknowledged: string | null };
export type DiffRow = { kind: "role" | "fit" | "structure"; target: string; from: unknown; to: unknown; by: string;
                        reason: string; status: "APPLIED" | "PENDING"; proposal?: string };
export type OverallStudy = StudyView & { role: Role; userLocked: boolean; reason: string; rationale: string };
export type ParamNode = { id: string; value: number | string | null; unit: string | null; status: string; source?: string | null;
                          fit: FitChoice | null; candidate_at: string[] };
export type PlanView = {
  plan: ModelPlan;
  artifact: { version: number; status: "DRAFT" | "APPROVED" | "SUPERSEDED" | "STALE"; stale_reasons: string[] };
  violations: Violation[];
  blocking: number;
  diff: DiffRow[];
  overall_data: { studies: OverallStudy[]; parameters: { id: string; value: number | string | null; unit: string | null; status: string }[] };
  d1: { binding: ParamNode[]; distribution: ParamNode[]; informed_by: string[];
        pathways: { process: string; kind: string; parameters: ParamNode[] }[] };
  d2: { absorption: ParamNode[]; dissolution: { id: string; label: string; release_model: string }[];
        lanes: { name: string; release: string; parameters: { id: string; value: unknown; unit: string | null }[];
                 studies: { study_id: string; food_state: string; role: Role }[] }[];
        food_effect_in_question: boolean; measured_fed_solubility: boolean };
  map: { status: string; version: number; map_sha256: string;
         campaign: { compound: string; map_id: string; cpf_uri: string; cpf_sha256: string; map_uri: string;
                     observed_uri: string; stages: string[]; question: string; model_risk: string } } | null;
  agents: { enabled: boolean };
  running: boolean;
  signature?: { signature_id: string; manifestation: string };
};

const base = (projectId: string) => `/api/v1/projects/${projectId}/plan`;

export const planApi = {
  get: (projectId: string) => apiGet<PlanView>(base(projectId)),
  place: (projectId: string, studyId: string, role: Role, reason: string, dryRun = false) =>
    apiSend<PlanView & { violations: Violation[] }>(`${base(projectId)}/placements/${encodeURIComponent(studyId)}${dryRun ? "?dry_run=true" : ""}`,
                                                   "PUT", { role, reason }),
  unlock: (projectId: string, studyId: string) => apiSend<PlanView>(`${base(projectId)}/placements/${encodeURIComponent(studyId)}:unlock`, "POST"),
  fit: (projectId: string, parameter: string, fit: { stages: string[]; lower: number; upper: number; scale: "linear" | "log"; reason: string }) =>
    apiSend<PlanView>(`${base(projectId)}/fits/${encodeURIComponent(parameter)}`, "PUT", fit),
  unfit: (projectId: string, parameter: string, reason: string) =>
    apiSend<PlanView>(`${base(projectId)}/fits/${encodeURIComponent(parameter)}:remove`, "POST", { reason }),
  structure: (projectId: string, key: string, value: unknown, reason: string) =>
    apiSend<PlanView>(`${base(projectId)}/structure`, "PUT", { key, value, reason }),
  acknowledge: (projectId: string, violationId: string, reason: string) =>
    apiSend<PlanView>(`${base(projectId)}/violations/${encodeURIComponent(violationId)}:acknowledge`, "POST", { reason }),
  decide: (projectId: string, proposalId: string, accept: boolean, reason: string) =>
    apiSend<PlanView>(`${base(projectId)}/proposals/${proposalId}:decide`, "POST", { accept, reason }),
  layout: (projectId: string, layout: Record<string, { x: number; y: number }>) => apiSend<PlanView>(`${base(projectId)}/layout`, "PUT", { layout }),
  rebase: (projectId: string) => apiSend<PlanView>(`${base(projectId)}:rebase`, "POST"),
  draft: (projectId: string) => apiSend<{ status: string }>(`${base(projectId)}:draft`, "POST"),
  sign: (projectId: string, note: string) => apiSend<PlanView>(`${base(projectId)}:sign`, "POST", { note }),
};

export type PlanEnvelope = Envelope<PlanView>;

/** The validator's verdict for one target (study or parameter), the most severe first. */
export function violationsFor(view: PlanView, target: string): Violation[] {
  return view.violations.filter((v) => v.target === target).sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1));
}
