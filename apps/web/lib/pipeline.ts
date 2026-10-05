// The project start-up pipeline (P0–P6): phase statuses, versioned artifacts, their history and the audit trail.
// Server-side reads return `Live<T>` (data or the problem that prevented it), like every other read in the app.

import { serverRead, type Live } from "@/lib/api";

export type PhaseId = "P0" | "P1" | "P2" | "P3" | "P4" | "P5" | "P6";
export type PhaseStatus = "NOT_STARTED" | "IN_REVIEW" | "APPROVED" | "STALE";
export type ArtifactStatus = "DRAFT" | "APPROVED" | "SUPERSEDED" | "STALE";

export type ArtifactRef = { kind: string; id: string; version: number };

export type Approval = {
  ref: ArtifactRef;
  record_sha256: string;
  meaning: string;
  by: string;
  printed_name: string;
  at: string;
  signature_id: string | null;
  note: string;
};

export type ArtifactView<C = Record<string, unknown>> = {
  kind: string;
  id: string;
  version: number;
  sha256: string;
  status: ArtifactStatus;
  stale_reasons: string[];
  created_at: string;
  created_by: string;
  reason: string;
  derived_from: ArtifactRef[];
  approvals: Approval[];
  content?: C;
};

export type Change = { path: string; before: unknown; after: unknown; kind: "added" | "removed" | "changed" };

export type HistoryRow = {
  version: number;
  sha256: string;
  status: ArtifactStatus;
  created_at: string;
  created_by: string;
  reason: string;
  phase: PhaseId;
  approvals: Approval[];
  changes: Change[];
};

export type Phases = {
  phases: { phase: PhaseId; label: string; status: PhaseStatus }[];
  stale: { ref: ArtifactRef; reasons: string[] }[];
};

export type AuditEventView = {
  seq: number;
  occurred_at: string;
  actor: string;
  action: string;
  resource_type: string;
  resource_id: string;
  before: unknown;
  after: unknown;
  reason: string | null;
  row_hash: string;
};

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

export async function getAudit(projectId: string): Promise<Live<{ chain_verifies: boolean; events: AuditEventView[] }>> {
  return serverRead(`/api/v1/projects/${projectId}/audit`);
}
