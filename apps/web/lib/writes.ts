// Client-side write helpers for the campaign start and the escalations, through the one client in lib/api.ts, each typed by
// its route; the campaign start and the escalation decision answer without the envelope and go through `post`.

import { post, type Narrow, type Schema } from "@/lib/api";

// The campaign starts from the MAP signed on Review & sign (plan:sign stages its inputs; the owner's decision 2 of
// 2026-11-11). campaign:prepare and a bare map_approval signature stay in the API for scripts and CI, not in the web app.
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
