// Client-side write helpers for the guided create-project flow, the campaign start and the escalations, through the
// one client in lib/api.ts, each typed by its route; signatures, the campaign start and the escalation decision answer
// without the envelope and go through `post`.

import { post, send, type Narrow, type Schema } from "@/lib/api";

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
  const env = await post("/api/v1/projects/{project_id}/signatures", { project_id: projectId }, {
    meaning: "Approved", record_type: "map_approval", record_id: body.record_id, record_sha256: body.record_sha256,
  });
  return { ok: !env.errors.length, error: env.errors[0]?.message };
}

export async function startCampaign(
  projectId: string,
  body: Schema<"CampaignStartRequest">,
): Promise<{ campaign_id?: string; status?: string; error?: string }> {
  const env = await post("/api/v1/projects/{project_id}/campaigns", { project_id: projectId }, body);
  return { campaign_id: env.data?.campaign_id, status: env.data?.status, error: env.errors[0]?.message };
}

/** A signed decision on an escalated stage (ResolveRequest: retry / accept_best / abort / approve, or for a failed
 *  external validation learn / new_evidence). The answer is EscalationResolved, or the API's reason on refusal. */
export function resolveEscalation(campaignId: string, stage: string, body: Schema<"ResolveRequest">) {
  return post("/api/v1/campaigns/{campaign_id}/stages/{stage}/escalation:resolve", { campaign_id: campaignId, stage }, body);
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
