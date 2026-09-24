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

/** A server-side read: the data, or what went wrong. Pages show the problem; they never substitute sample data,
 *  because a page that looks live but is not hides the real fault (and fake numbers must never pass as results). */
export type Live<T> = { data: T | null; problem: string | null; notFound: boolean };

export async function serverRead<T>(path: string): Promise<Live<T>> {
  let response: Response;
  try {
    response = await fetch(`${SERVER_API_BASE}${path}`, {
      headers: { Authorization: `Bearer ${WEB_TOKEN}` },
      cache: "no-store",
    });
  } catch (err) {
    const cause = (err as { cause?: { code?: string } })?.cause?.code ?? (err as Error)?.message ?? "no answer";
    return { data: null, notFound: false,
             problem: `The API at ${SERVER_API_BASE} is not reachable (${cause}). Start it, or point MODELER_API_BASE at it.` };
  }
  if (response.status === 404) return { data: null, notFound: true, problem: null };
  if (!response.ok) {
    let detail = "";
    try { detail = ((await response.json()) as { detail?: string }).detail ?? ""; } catch { /* not JSON */ }
    return { data: null, notFound: false, problem: `The API answered HTTP ${response.status}${detail ? `: ${detail}` : ""}` };
  }
  const env = (await response.json()) as Envelope<T>;
  if (env.errors?.length) return { data: null, notFound: false, problem: env.errors[0].message };
  return { data: env.data, notFound: false, problem: null };
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
