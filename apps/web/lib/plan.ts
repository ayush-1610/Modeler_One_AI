// P5 · model plan (plan §11, review layer L3): the plan page's types and the calls the canvas makes.
// The ModelPlan JSON is the record; the canvas only renders it and sends changes, each with a reason.

import { send, type Schema } from "@/lib/api";

// The plan page as the API sends it (generated from the contract; the plan is the owner's ModelPlan model).
export type PlanView = Schema<"PlanPage">;
export type ModelPlan = Schema<"ModelPlan">;
export type Role = Schema<"Placement">["role"];
export type FitChoice = Schema<"FitChoice">;
export type Violation = Schema<"Violation">;
export type DiffRow = Schema<"DiffRow">;
export type OverallStudy = Schema<"OverallStudy">;
export type ParamNode = Schema<"ParamNode">;
// D-14: a change after the MAP was signed, pending until the MIDD lead signs it into a new MAP version.
export type Deviation = Schema<"Deviation">;

export const ROLE_LABEL: Record<Role, string> = {
  S1: "S1 · IV disposition", S2: "S2 · oral absorption", S3: "S3 · formulation / fed",
  S5: "S5 · external validation", S6: "S6 · application", SUPPORTIVE: "supportive",
};

const project = (projectId: string) => ({ project_id: projectId });

// The canvas's changes, each a typed route; the page reads the plan with useResource and runs these with useMutation.
export const planApi = {
  place: (projectId: string, studyId: string, role: Role, reason: string, dryRun = false) =>
    send("put", "/api/v1/projects/{project_id}/plan/placements/{study_id}", { project_id: projectId, study_id: studyId },
         { role, reason }, dryRun ? { dry_run: "true" } : undefined),
  fit: (projectId: string, parameter: string, fit: Schema<"FitRequest">) =>
    send("put", "/api/v1/projects/{project_id}/plan/fits/{parameter}", { project_id: projectId, parameter }, fit),
  unfit: (projectId: string, parameter: string, reason: string) =>
    send("post", "/api/v1/projects/{project_id}/plan/fits/{parameter}:remove", { project_id: projectId, parameter }, { reason }),
  structure: (projectId: string, key: Schema<"StructureRequest">["key"], value: unknown, reason: string) =>
    send("put", "/api/v1/projects/{project_id}/plan/structure", project(projectId), { key, value, reason }),
  acknowledge: (projectId: string, violationId: string, reason: string) =>
    send("post", "/api/v1/projects/{project_id}/plan/violations/{violation_id}:acknowledge",
         { project_id: projectId, violation_id: violationId }, { reason }),
  decide: (projectId: string, proposalId: string, accept: boolean, reason: string) =>
    send("post", "/api/v1/projects/{project_id}/plan/proposals/{proposal_id}:decide",
         { project_id: projectId, proposal_id: proposalId }, { accept, reason }),
  layout: (projectId: string, layout: Schema<"LayoutRequest">["layout"]) =>
    send("put", "/api/v1/projects/{project_id}/plan/layout", project(projectId), { layout }),
  rebase: (projectId: string) => send("post", "/api/v1/projects/{project_id}/plan:rebase", project(projectId)),
  draft: (projectId: string) => send("post", "/api/v1/projects/{project_id}/plan:draft", project(projectId)),
  sign: (projectId: string, note: string) => send("post", "/api/v1/projects/{project_id}/plan:sign", project(projectId), { note }),
  setBlinding: (projectId: string, on: boolean, reason: string) =>
    send("put", "/api/v1/projects/{project_id}/blinding", project(projectId), { on, reason }),
};

/** The validator's verdict for one target (study or parameter), the most severe first. */
export function violationsFor(view: PlanView, target: string): Violation[] {
  return view.violations.filter((v) => v.target === target).sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1));
}
