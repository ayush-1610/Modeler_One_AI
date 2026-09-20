export type ApiError = { code: string; location?: string; message: string };

export type Envelope<T> = {
  data: T | null;
  meta: { request_id: string; timestamp: string; api_version: string };
  errors: ApiError[];
};

// Server components fetch the API directly (server-to-server); the browser uses same-origin "/api/..." paths
// that next.config proxies to the backend. In production the user's forwarded OIDC token replaces the dev one.
const SERVER_API_BASE = process.env.MODELER_API_BASE ?? "http://127.0.0.1:8000";
const WEB_TOKEN = process.env.MODELER_WEB_TOKEN ?? "dev";

/** Server-side GET returning the envelope's `data`, or null if the API is unreachable or returns an error. */
export async function serverGet<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${SERVER_API_BASE}${path}`, {
      headers: { Authorization: `Bearer ${WEB_TOKEN}` },
      cache: "no-store",
    });
    if (!response.ok) return null;
    const env = (await response.json()) as Envelope<T>;
    return env.errors?.length ? null : env.data;
  } catch {
    return null; // API not running — caller falls back to sample data so the UI still renders
  }
}

export async function apiPost<T>(path: string, body: unknown): Promise<Envelope<T>> {
  const response = await fetch(path, {
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
  const response = await fetch(path, {
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
