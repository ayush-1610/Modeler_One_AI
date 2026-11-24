// Client-side write helpers for the campaign's preparation and start, the MAP signature and the escalations, through the
// one client in lib/api.ts, each typed by its route; signatures, the campaign start and the escalation decision answer
// without the envelope and go through `post`.

import { post, send, type Schema } from "@/lib/api";

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

