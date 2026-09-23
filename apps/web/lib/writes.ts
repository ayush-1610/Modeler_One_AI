// Client-side write helpers for the guided create-project flow. Each POSTs/PUTs with a bearer token; under
// single-node dev auth any bearer is accepted, so NEXT_PUBLIC_DEMO_TOKEN ?? "dev" is enough.

import type { Envelope } from "@/lib/api";

// Browser writes go to this same origin ("/api/..."); next.config proxies them to the backend, so there is
// one URL and no CORS. The dev bearer is accepted by dev auth; in production the user's OIDC token is used.
export const WEB_TOKEN = process.env.NEXT_PUBLIC_DEMO_TOKEN ?? "dev";

async function authed<T>(path: string, method: "POST" | "PUT", body: unknown): Promise<Envelope<T>> {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${WEB_TOKEN}` },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return (await res.json()) as Envelope<T>;
}

export type CreatedProject = { id: string; name: string; compounds: string[]; questions: { id: string }[] };
export type PrepareResult = {
  map_id: string;
  compound: string;
  cpf_uri: string;
  cpf_sha256: string;
  map_uri: string;
  map_sha256: string;
  observed_uri: string;
  stages: string[];
  tier: string;
  studies: { study_id: string; assignment: string }[];
};

export function createProject(body: { name: string; compound: string; question?: string; risk?: string; model_risk?: string }) {
  return authed<CreatedProject>("/api/v1/projects", "POST", body);
}

export function putCpf(projectId: string, compound: string, cpf: unknown) {
  return authed<unknown>(`/api/v1/projects/${projectId}/compounds/${compound}/cpf`, "PUT", cpf);
}

export function uploadStudies(projectId: string, studies: unknown[]) {
  return authed<{ stored: number }>(`/api/v1/projects/${projectId}/studies`, "POST", { studies });
}

export function prepareCampaign(
  projectId: string,
  questionId: string,
  body: { compound: string; stages?: string[]; model_risk?: string },
) {
  return authed<PrepareResult>(`/api/v1/projects/${projectId}/questions/${questionId}/campaign:prepare`, "POST", body);
}

// The signatures and campaign-start endpoints return a raw object (not the envelope), so read them directly.
async function rawPost<T>(path: string, body: unknown): Promise<{ ok: boolean; body: T }> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${WEB_TOKEN}` },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return { ok: res.ok, body: (await res.json()) as T };
}

/** Sign the MAP (Part 11). Returns whether the signature was accepted (loa2 step-up satisfied). */
export async function signMap(projectId: string, body: { record_id: string; record_sha256: string }): Promise<boolean> {
  const { ok } = await rawPost(`/api/v1/projects/${projectId}/signatures`, {
    meaning: "Approved", record_type: "map_approval", record_id: body.record_id, record_sha256: body.record_sha256,
  });
  return ok;
}

export async function startCampaign(
  projectId: string,
  body: {
    compound: string;
    map_id: string;
    cpf_uri: string;
    cpf_sha256: string;
    map_uri: string;
    observed_uri: string;
    question?: string;
    model_risk?: string;
    stages?: string[];
  },
): Promise<{ campaign_id?: string; status?: string }> {
  const { body: data } = await rawPost<{ campaign_id?: string; status?: string }>(
    `/api/v1/projects/${projectId}/campaigns`, body);
  return data;
}

/** Resolve an escalated stage from the review inbox (retry / accept_best / abort). Every decision is an
 *  approval and is signed server-side from the session's step-up, so nothing moves without a signature. */
export async function resolveEscalation(
  campaignId: string,
  stage: string,
  body: { action: "retry" | "accept_best" | "abort"; note?: string },
): Promise<{ ok: boolean; status?: string; detail?: string; signature?: { manifestation: string } }> {
  const { ok, body: data } = await rawPost<{ status?: string; detail?: string; signature?: { manifestation: string } }>(
    `/api/v1/campaigns/${campaignId}/stages/${stage}/escalation:resolve`, body);
  return { ok, ...data };
}
