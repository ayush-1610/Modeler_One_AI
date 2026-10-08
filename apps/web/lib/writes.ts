// Client-side write helpers for the guided create-project flow, the campaign start and the escalations. They call the
// API through the one client in lib/api.ts; these routes are not typed in the contract yet, so the answers are typed here.

import { apiGet, apiSend, rawPost, type Schema } from "@/lib/api";

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
  origins?: Record<string, string | null>;
  not_evaluable?: string[];
};

export function createProject(body: { name: string; compound: string; question?: string; risk?: string; model_risk?: string;
                                      exploratory?: boolean }) {
  return apiSend<CreatedProject>("/api/v1/projects", "POST", body);
}

export function putCpf(projectId: string, compound: string, cpf: unknown) {
  return apiSend<unknown>(`/api/v1/projects/${projectId}/compounds/${compound}/cpf`, "PUT", cpf);
}

export function uploadStudies(projectId: string, studies: unknown[]) {
  return apiSend<{ stored: number }>(`/api/v1/projects/${projectId}/studies`, "POST", { studies });
}

export function prepareCampaign(
  projectId: string,
  questionId: string,
  body: { compound: string; stages?: string[]; model_risk?: string },
) {
  return apiSend<PrepareResult>(`/api/v1/projects/${projectId}/questions/${questionId}/campaign:prepare`, "POST", body);
}

/** Sign the MAP (Part 11). Returns whether the signature was accepted (loa2 step-up satisfied), and why not. */
export async function signMap(
  projectId: string,
  body: { record_id: string; record_sha256: string },
): Promise<{ ok: boolean; error?: string }> {
  const { ok, error } = await rawPost(`/api/v1/projects/${projectId}/signatures`, {
    meaning: "Approved", record_type: "map_approval", record_id: body.record_id, record_sha256: body.record_sha256,
  });
  return { ok, error };
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
): Promise<{ campaign_id?: string; status?: string; error?: string }> {
  const { body: data, error } = await rawPost<{ campaign_id?: string; status?: string }>(
    `/api/v1/projects/${projectId}/campaigns`, body);
  return { ...data, error };
}

/** Resolve an escalated stage from the review inbox (retry / accept_best / abort). Every decision is an
 *  approval and is signed server-side from the session's step-up, so nothing moves without a signature. */
/** A signed decision on an escalated stage (ResolveRequest: retry / accept_best / abort / approve, or for a failed
 *  external validation learn / new_evidence). The answer is EscalationResolved, or the API's `detail` on refusal. */
export async function resolveEscalation(
  campaignId: string,
  stage: string,
  body: Schema<"ResolveRequest">,
): Promise<{ ok: boolean; detail?: string } & Partial<Schema<"EscalationResolved">>> {
  const { ok, body: data, error } = await rawPost<Partial<Schema<"EscalationResolved">> & { detail?: string }>(
    `/api/v1/campaigns/${campaignId}/stages/${stage}/escalation:resolve`, body);
  return { ok, ...data, detail: data.detail ?? error };
}

// --- project starting points (GET /templates) ----------------------------------------------------------------

export type TemplateSummary = {
  id: string;
  name: string;
  compound: string;
  question: string;
  model_risk: string;
  real_data: boolean;
  blank?: boolean; // the user's own compound: the S0 parameters, each missing, and no studies yet
  description: string;
};

export type StudyRow = {
  study_id: string;
  reference?: string;
  route: string;
  dose_mg: number;
  formulation?: string;
  formulation_name?: string;
  food_state?: string;
  design?: string;
  n?: number;
  special_population?: string | null;
  origin?: string | null;
  profile: { times: number[]; values: number[]; time_unit: string; unit: string };
};

export type TemplateContent = TemplateSummary & {
  cpf: {
    compound: string;
    parameters: {
      id: string; value: unknown; unit?: string | null; status: string;
      provenance?: { source_type: string; reference?: string } | null;
    }[];
  };
  studies: StudyRow[];
  skipped: string[];
  notes: string[];
  source: string;
};

export function listTemplates() {
  return apiGet<{ templates: TemplateSummary[] }>("/api/v1/templates");
}

export function getTemplate(id: string) {
  return apiGet<TemplateContent>(`/api/v1/templates/${id}`);
}
