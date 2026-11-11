// The project start-up pipeline: the redesign's four steps, what has gone stale, versioned artifacts, their history and the audit trail.
// Server-side reads return `Live<T>` (data or the problem that prevented it), like every other read in the app.

// The reads are wrapped in React's cache(): within one server render, a page and the components in it (the step bar, the
// page's own checks) share one request per read instead of asking the API again. It never outlives the request: every
// page still reads the API afresh (serverGet stays `no-store`), so a status shown is never an earlier one (audit item 9).
import { cache } from "react";

import { narrow, serverGet, type Live, type Narrow, type Schema } from "@/lib/api";
import { plain } from "@/lib/plain";

// The answers are the API's generated response models (lib/api-types.ts); an artifact's stored content is the caller's.
export type ArtifactStatus = Schema<"ArtifactStatus">;
export type ArtifactRef = Schema<"Ref">;
export type Approval = Schema<"ApprovalView">;
export type ArtifactView<C = Record<string, unknown>> = Narrow<Schema<"VersionView">, { content?: C | null }>;
export type Change = Schema<"ChangeView">;
export type HistoryRow = Schema<"HistoryRow">;
export type StaleArtifact = Schema<"StaleArtifact">;
export type AuditEventView = Schema<"AuditEventView">;

// The redesigned flow (docs/plans/2026-10-19-p0-p5-redesign.md §3): four steps, each read from content, not approvals.
export type StepId = Schema<"StepRow">["step"];
export type StepState = Schema<"StepRow">["state"];
export type StepRow = Schema<"StepRow">;

/** Where each step is worked on. */
export const STEP_ROUTES: Record<StepId, (projectId: string) => string> = {
  start: (p) => `/projects/${p}/start`,
  inputs: (p) => `/projects/${p}/inputs`,
  review: (p) => `/projects/${p}/plan`,
  run: (p) => `/projects/${p}`,
};

export const getSteps = cache(async (projectId: string): Promise<Live<StepRow[]>> => {
  const live = await serverGet("/api/v1/projects/{project_id}/steps", { project_id: projectId });
  // the reasons as a person reads them: the decision numbers stay in the record (lib/plain.ts)
  return { ...live, data: live.data ? live.data.steps.map((s) => ({ ...s, reasons: s.reasons.map(plain) })) : null };
});

/** What was made from inputs that have since changed, with why. */
export const getStale = cache(async (projectId: string): Promise<Live<StaleArtifact[]>> => {
  const live = await serverGet("/api/v1/projects/{project_id}/stale", { project_id: projectId });
  return { ...live, data: live.data ? live.data.stale : null };
});

export const getArtifacts = cache(async (projectId: string, kind?: string): Promise<Live<ArtifactView[]>> => {
  const live = await serverGet("/api/v1/projects/{project_id}/artifacts", { project_id: projectId }, { kind });
  return { ...live, data: live.data ? live.data.artifacts : null };
});

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
