export type ApiError = { code: string; location?: string; message: string };

export type Envelope<T> = {
  data: T | null;
  meta: { request_id: string; timestamp: string; api_version: string };
  errors: ApiError[];
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function apiPost<T>(path: string, body: unknown): Promise<Envelope<T>> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return (await response.json()) as Envelope<T>;
}

export type Rating = "low" | "medium" | "high";

// --- action wrappers for the endpoints the backend already exposes -------------------------------

export type SignaturePayload = {
  meaning: string;
  record_type: string;
  record_id: string;
  record_sha256: string;
};

/** POST a Part 11 electronic signature (requires an loa2 step-up bearer token from Keycloak). */
export async function createSignature(projectId: string, body: SignaturePayload, token: string) {
  return apiPostAuth(`/api/v1/projects/${projectId}/signatures`, body, token);
}

/** POST an escalation decision. Signed options carry a signature id obtained from createSignature. */
export async function decideEscalation(
  campaignId: string,
  stage: string,
  body: { option_id: string; rationale: string; signature_id?: string },
  token: string,
) {
  return apiPostAuth(`/api/v1/campaigns/${campaignId}/stages/${stage}/escalation:decide`, body, token);
}

async function apiPostAuth<T>(path: string, body: unknown, token: string): Promise<Envelope<T>> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return (await response.json()) as Envelope<T>;
}

export type QuestionStatus = {
  id: string;
  question: string;
  application: string;
  modelRisk: Rating | null;
  stage: "planning" | "evaluation" | "reporting" | "signed";
  failingCriteria: number;
};
