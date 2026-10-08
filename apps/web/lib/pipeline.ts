// The project start-up pipeline (P0–P6): phase statuses, versioned artifacts, their history and the audit trail.
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
