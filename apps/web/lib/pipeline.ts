// The project start-up pipeline (P0–P6): phase statuses, versioned artifacts, their history and the audit trail.
// Server-side reads return `Live<T>` (data or the problem that prevented it), like every other read in the app.

import { serverRead, type Live, type Narrow, type Schema } from "@/lib/api";

// The answers are the API's generated response models (lib/api-types.ts); an artifact's stored content is the caller's.
export type PhaseId = Schema<"PhaseRow">["phase"];
export type PhaseStatus = Schema<"PhaseStatus">;
export type ArtifactStatus = Schema<"ArtifactStatus">;
export type ArtifactRef = Schema<"Ref">;
export type Approval = Schema<"ApprovalView">;
export type ArtifactView<C = Record<string, unknown>> = Narrow<Schema<"VersionView">, { content?: C }>;
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
  return serverRead<Phases>(`/api/v1/projects/${projectId}/phases`);
}

export async function getArtifacts(projectId: string, kind?: string): Promise<Live<ArtifactView[]>> {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  const live = await serverRead<{ artifacts: ArtifactView[] }>(`/api/v1/projects/${projectId}/artifacts${query}`);
  return { ...live, data: live.data ? live.data.artifacts : null };
}

export function getArtifact<C>(projectId: string, kind: string, id: string): Promise<Live<ArtifactView<C>>> {
  return serverRead<ArtifactView<C>>(`/api/v1/projects/${projectId}/artifacts/${kind}/${encodeURIComponent(id)}`);
}

export async function getHistory(projectId: string, kind: string, id: string): Promise<Live<HistoryRow[]>> {
  const live = await serverRead<{ versions: HistoryRow[] }>(
    `/api/v1/projects/${projectId}/artifacts/${kind}/${encodeURIComponent(id)}/history`);
  return { ...live, data: live.data ? live.data.versions : null };
}

export async function getAudit(projectId: string): Promise<Live<Schema<"AuditTrail">>> {
  return serverRead(`/api/v1/projects/${projectId}/audit`);
}
