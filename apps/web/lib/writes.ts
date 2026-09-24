// Client-side write helpers for the guided create-project flow. Each POSTs/PUTs with a bearer token; under
// single-node dev auth any bearer is accepted, so NEXT_PUBLIC_DEMO_TOKEN ?? "dev" is enough.

import type { Envelope } from "@/lib/api";

// Browser writes go to this same origin ("/api/..."); next.config proxies them to the backend, so there is
// one URL and no CORS. The dev bearer is accepted by dev auth; in production the user's OIDC token is used.
export const WEB_TOKEN = process.env.NEXT_PUBLIC_DEMO_TOKEN ?? "dev";

/** Turn any non-success answer into a readable message: the API's own `detail` when it sent one, else the HTTP
 *  status, with a hint when the web server's proxy could not reach the API at all. */
async function failure(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  try {
    const body = JSON.parse(text) as { detail?: unknown; errors?: { message: string }[] };
    if (body.errors?.length) return body.errors[0].message;
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      // FastAPI validation errors: [{loc: [...], msg}] -> "studies.0.dose_mg: field required"
      return body.detail
        .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? "invalid"}`)
        .join("; ");
    }
  } catch {
    // not JSON: the proxy's own error page
  }
  if (res.status >= 500) {
    return `The API did not answer (HTTP ${res.status}). Is the backend running, and does the web server's ` +
      "MODELER_API_BASE point at it?";
  }
  return `HTTP ${res.status} ${res.statusText}`.trim();
}

function errorEnvelope<T>(message: string): Envelope<T> {
  return { data: null, meta: { request_id: "", timestamp: "", api_version: "" }, errors: [{ code: "HTTP", message }] };
}

async function authed<T>(path: string, method: "GET" | "POST" | "PUT", body?: unknown): Promise<Envelope<T>> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${WEB_TOKEN}` },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return errorEnvelope("The web server could not be reached. Check your connection to it.");
  }
  if (!res.ok) return errorEnvelope(await failure(res));
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
async function rawPost<T>(path: string, body: unknown): Promise<{ ok: boolean; body: T; error?: string }> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${WEB_TOKEN}` },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return { ok: false, body: {} as T, error: "The web server could not be reached. Check your connection to it." };
  }
  if (!res.ok) return { ok: false, body: {} as T, error: await failure(res) };
  return { ok: true, body: (await res.json()) as T };
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
export async function resolveEscalation(
  campaignId: string,
  stage: string,
  body: { action: "retry" | "accept_best" | "abort" | "approve"; note?: string },
): Promise<{ ok: boolean; status?: string; detail?: string; signature?: { manifestation: string } }> {
  const { ok, body: data, error } = await rawPost<{ status?: string; detail?: string; signature?: { manifestation: string } }>(
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
  profile: { times: number[]; values: number[]; time_unit: string; unit: string };
};

export type TemplateContent = TemplateSummary & {
  cpf: { compound: string; parameters: { id: string; value: unknown; unit?: string | null; status: string }[] };
  studies: StudyRow[];
  skipped: string[];
  notes: string[];
  source: string;
};

export function listTemplates() {
  return authed<{ templates: TemplateSummary[] }>("/api/v1/templates", "GET");
}

export function getTemplate(id: string) {
  return authed<TemplateContent>(`/api/v1/templates/${id}`, "GET");
}
