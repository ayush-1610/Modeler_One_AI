// The project start-up pipeline: the redesign's four steps, P0–P6 phase statuses, versioned artifacts, their history and the audit trail.
// Server-side reads return `Live<T>` (data or the problem that prevented it), like every other read in the app.

import { narrow, serverGet, type Live, type Narrow, type Schema } from "@/lib/api";

// The answers are the API's generated response models (lib/api-types.ts); an artifact's stored content is the caller's.
export type PhaseId = Schema<"PhaseRow">["phase"];
export type PhaseStatus = Schema<"PhaseStatus">;
export type ArtifactStatus = Schema<"ArtifactStatus">;
export type ArtifactRef = Schema<"Ref">;
export type Approval = Schema<"ApprovalView">;
export type ArtifactView<C = Record<string, unknown>> = Narrow<Schema<"VersionView">, { content?: C | null }>;
export type Change = Schema<"ChangeView">;
export type HistoryRow = Schema<"HistoryRow">;
export type Phases = Schema<"Phases">;
export type AuditEventView = Schema<"AuditEventView">;

/** Where each phase is reviewed. */
export const PHASE_ROUTES: Record<PhaseId, (projectId: string) => string> = {
  P0: (p) => `/projects/${p}/brief`,
  P1: (p) => `/projects/${p}/brief`,
  P2: (p) => `/projects/${p}/evidence`,
  P3: (p) => `/projects/${p}/client-data`,
  P4: (p) => `/projects/${p}/inputs`,
  P5: (p) => `/projects/${p}/plan`,
  P6: (p) => `/projects/${p}`,
};

// The redesigned flow (docs/plans/2026-10-19-p0-p5-redesign.md §3): four steps, each read from content, not approvals.
export type StepId = Schema<"StepRow">["step"];
export type StepState = Schema<"StepRow">["state"];
export type StepRow = Schema<"StepRow">;

/** Where each step is worked on. Inputs still spans three pages until they become one workspace (R3). */
export const STEP_ROUTES: Record<StepId, (projectId: string) => string> = {
  start: (p) => `/projects/${p}/brief`,
  inputs: (p) => `/projects/${p}/inputs`,
  review: (p) => `/projects/${p}/plan`,
  run: (p) => `/projects/${p}`,
};
export const INPUTS_PAGES: { id: string; label: string; href: (projectId: string) => string }[] = [
  { id: "evidence", label: "Literature", href: (p) => `/projects/${p}/evidence` },
  { id: "client-data", label: "Client data", href: (p) => `/projects/${p}/client-data` },
  { id: "inputs", label: "Model inputs", href: (p) => `/projects/${p}/inputs` },
];

export async function getSteps(projectId: string): Promise<Live<StepRow[]>> {
  const live = await serverGet("/api/v1/projects/{project_id}/steps", { project_id: projectId });
  return { ...live, data: live.data ? live.data.steps : null };
}

export function getPhases(projectId: string): Promise<Live<Phases>> {
  return serverGet("/api/v1/projects/{project_id}/phases", { project_id: projectId });
}

export async function getArtifacts(projectId: string, kind?: string): Promise<Live<ArtifactView[]>> {
  const live = await serverGet("/api/v1/projects/{project_id}/artifacts", { project_id: projectId }, { kind });
  return { ...live, data: live.data ? live.data.artifacts : null };
}

export async function getArtifact<C>(projectId: string, kind: string, id: string): Promise<Live<ArtifactView<C>>> {
  const live = await serverGet("/api/v1/projects/{project_id}/artifacts/{kind}/{artifact_id}", { project_id: projectId, kind, artifact_id: id });
  return { ...live, data: live.data ? narrow<ArtifactView<C>>(live.data) : null };
}

export async function getHistory(projectId: string, kind: string, id: string): Promise<Live<HistoryRow[]>> {
  const live = await serverGet("/api/v1/projects/{project_id}/artifacts/{kind}/{artifact_id}/history",
                               { project_id: projectId, kind, artifact_id: id });
  return { ...live, data: live.data ? live.data.versions : null };
}

export function getAudit(projectId: string): Promise<Live<Schema<"AuditTrail">>> {
  return serverGet("/api/v1/projects/{project_id}/audit", { project_id: projectId });
}
