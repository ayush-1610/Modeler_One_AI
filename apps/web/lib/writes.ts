// Client-side write helpers for the guided create-project flow, the campaign start and the escalations, through the
// one client in lib/api.ts. The project writes are typed by the contract (phase 9c); signatures, the campaign start and
// the escalation decision answer without the envelope and are typed here until phase 9d.

import { rawPost, send, type Narrow, type Schema } from "@/lib/api";

export type PrepareResult = Schema<"CampaignInputs">;

export function createProject(body: Schema<"ProjectCreate">) {
  return send("post", "/api/v1/projects", {}, body);
}

/** Put a compound's CPF; the JSON a person edited is the body, checked by the API against the CPF schema. */
export function putCpf(projectId: string, compound: string, cpf: unknown) {
  return send("put", "/api/v1/projects/{project_id}/compounds/{compound}/cpf", { project_id: projectId, compound },
              cpf as Schema<"CPF">);
}

/** Upload observed studies; the rows a person edited are the body, checked by the API against the upload schema. */
export function uploadStudies(projectId: string, studies: unknown[]) {
  return send("post", "/api/v1/projects/{project_id}/studies", { project_id: projectId },
              { studies: studies as Schema<"StudiesUpload">["studies"] });
}

export function prepareCampaign(projectId: string, questionId: string, body: Schema<"PrepareRequest">) {
  return send("post", "/api/v1/projects/{project_id}/questions/{question_id}/campaign:prepare",
              { project_id: projectId, question_id: questionId }, body);
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

// --- project starting points (GET /templates; the wizard reads them with useResource) ---------------------------

export type TemplateSummary = Schema<"TemplateSummary">;

/** A template's study, in the upload shape it is sent back in (the template's own document). */
export type TemplateStudy = {
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

/** A template in full; its CPF and studies are the template's documents, typed here as the wizard edits them. */
export type TemplateContent = Narrow<Schema<"TemplateContent">, {
  cpf: {
    compound: string;
    parameters: {
      id: string; value: unknown; unit?: string | null; status: string;
      provenance?: { source_type: string; reference?: string } | null;
    }[];
  };
  studies: TemplateStudy[];
}>;
