// The web app's one API client (phase 7, rule B6). Server components read with `serverGet` / `serverRead` (server to
// server); the browser uses `get` / `send` / `upload` on same-origin "/api/..." paths that next.config proxies to the
// backend. A typed call names its route as the contract does ("/api/v1/projects/{project_id}/brief"): the path
// parameters, the body and the answer's type follow from the route, so a page cannot call a route that does not exist
// or read a shape the API does not send. Routes the contract does not type yet use `apiGet` / `apiSend` / `serverRead`
// with a hand-written type.

import type { components, paths } from "./api-types";

/** A response model of the API, generated from docs/api/openapi.json into lib/api-types.ts (`npm run api-types`;
 *  `npm run typecheck` fails when the file is older than the snapshot). Use it instead of hand-writing an answer's
 *  shape: `Schema<"BriefPage">`. Stored artifact content (a brief, a plan) is typed by hand where the API sends it as
 *  an open object. */
export type Schema<Name extends keyof components["schemas"]> = components["schemas"][Name];

/** A generated answer with some of its open-object fields (stored content the API sends untyped) typed by the page.
 *  Only fields the answer has can be narrowed, so a field the API drops or renames fails the typecheck:
 *  `Narrow<Schema<"BriefPage">, { brief: Brief }>`. */
export type Narrow<S, N extends { [K in keyof N]: K extends keyof S ? unknown : never }> = Omit<S, keyof N> & N;

export type ApiError = { code: string; location?: string; message: string };

export type Envelope<T> = {
  data: T | null;
  meta: { request_id: string; timestamp: string; api_version: string };
  errors: ApiError[];
};

export type Rating = "low" | "medium" | "high";

// --- routes, as the contract names them ---------------------------------------------------------------------

/** A route of the API, as the contract names it: "/api/v1/projects/{project_id}/brief". */
export type Route = keyof paths;
type Method = "get" | "post" | "put";
type Operation<R extends Route, M extends Method> = NonNullable<paths[R][M]>;
/** The routes that answer to a method. */
export type RouteFor<M extends Method> = { [R in Route]: [Operation<R, M>] extends [never] ? never : R }[Route];
type Success<O> = O extends { responses: infer Rs } ? Rs[Extract<keyof Rs, 200 | 201 | 202>] : never;
type Json<X> = X extends { content: { "application/json": infer J } } ? J : never;
/** The JSON a route answers with on success (the envelope, for a route that sends one). */
export type Answer<R extends Route, M extends Method> = Json<Success<Operation<R, M>>>;
/** The `data` of a route's envelope. */
export type Data<R extends Route, M extends Method> = Answer<R, M> extends { data: infer D } ? D : never;
/** The JSON body a route takes. */
export type Body<R extends Route, M extends Method> =
  Operation<R, M> extends { requestBody?: { content: { "application/json": infer B } } } ? B : never;
type ParamNames<R extends string> = R extends `${string}{${infer P}}${infer Rest}` ? P | ParamNames<Rest> : never;
/** The path parameters a route names: `{ project_id: string }`. */
export type Params<R extends string> = { [K in ParamNames<R>]: string };
/** Read a typed answer as the page's narrowed view of it (`Narrow<…>`), where the stored content the API sends as an
 *  open object is the page's to type. The answer must have every key of the view: `narrow<BriefView>(env.data)`. */
export function narrow<T>(data: { [K in keyof T]: unknown }): T {
  return data as T;
}

/** The URL of a route: its parameters filled in (each encoded) and the query appended (undefined values left out). */
export function path<R extends Route>(route: R, params: Params<R>, query?: Record<string, string | undefined>): string {
  let out: string = route;
  for (const [name, value] of Object.entries(params as Record<string, string>)) {
    out = out.replace(`{${name}}`, encodeURIComponent(value));
  }
  const pairs = Object.entries(query ?? {}).filter((pair): pair is [string, string] => pair[1] !== undefined);
  return pairs.length ? `${out}?${new URLSearchParams(pairs).toString()}` : out;
}

// --- server components: server-to-server reads --------------------------------------------------------------

// In production the user's forwarded OIDC token replaces the dev one.
const SERVER_API_BASE = process.env.MODELER_API_BASE ?? "http://127.0.0.1:8000";
const SERVER_TOKEN = process.env.MODELER_WEB_TOKEN ?? "dev";

/** A server-side read: the data, or what went wrong. Pages show the problem; they never substitute sample data,
 *  because a page that looks live but is not hides the real fault (and fake numbers must never pass as results). */
export type Live<T> = { data: T | null; problem: string | null; notFound: boolean };

export async function serverRead<T>(url: string): Promise<Live<T>> {
  let response: Response;
  try {
    response = await fetch(`${SERVER_API_BASE}${url}`, {
      headers: { Authorization: `Bearer ${SERVER_TOKEN}` },
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

/** A typed server-side read of a route: `serverGet("/api/v1/projects/{project_id}/phases", { project_id })`. */
export function serverGet<R extends RouteFor<"get">>(
  route: R, params: Params<R>, query?: Record<string, string | undefined>,
): Promise<Live<Data<R, "get">>> {
  return serverRead<Data<R, "get">>(path(route, params, query));
}

// --- the browser: same-origin calls with the user's bearer ----------------------------------------------------

// The dev bearer is accepted by dev auth; in production the user's OIDC token is used.
export const BROWSER_TOKEN = process.env.NEXT_PUBLIC_DEMO_TOKEN ?? "dev";

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

const UNREACHABLE = "The web server could not be reached. Check your connection to it.";

async function request<T>(url: string, method: "GET" | "POST" | "PUT", body?: unknown): Promise<Envelope<T>> {
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${BROWSER_TOKEN}` },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return errorEnvelope(UNREACHABLE);
  }
  if (!res.ok) return errorEnvelope(await failure(res));
  return (await res.json()) as Envelope<T>;
}

async function multipart<T>(url: string, form: FormData): Promise<Envelope<T>> {
  let res: Response;
  try {
    res = await fetch(url, { method: "POST", headers: { Authorization: `Bearer ${BROWSER_TOKEN}` }, body: form, cache: "no-store" });
  } catch {
    return errorEnvelope(UNREACHABLE);
  }
  if (!res.ok) return errorEnvelope(await failure(res));
  return (await res.json()) as Envelope<T>;
}

/** A typed browser read: `get("/api/v1/projects/{project_id}/brief", { project_id })`. */
export function get<R extends RouteFor<"get">>(
  route: R, params: Params<R>, query?: Record<string, string | undefined>,
): Promise<Envelope<Data<R, "get">>> {
  return request(path(route, params, query), "GET");
}

/** A typed browser write; the body is the route's request model (an empty object when the route takes none). */
export function send<M extends "post" | "put", R extends RouteFor<M>>(
  method: M, route: R, params: Params<R>, body?: Body<R, M>, query?: Record<string, string | undefined>,
): Promise<Envelope<Data<R, M>>> {
  return request(path(route, params, query), method === "post" ? "POST" : "PUT", body ?? {});
}

/** A typed multipart upload (files and form fields); the browser sets the multipart boundary itself. */
export function upload<R extends RouteFor<"post">>(route: R, params: Params<R>, form: FormData): Promise<Envelope<Data<R, "post">>> {
  return multipart(path(route, params), form);
}

/** A browser read of a route the contract does not type yet (its answer type is the page's). */
export function apiGet<T>(url: string): Promise<Envelope<T>> {
  return request<T>(url, "GET");
}

/** A browser write to a route the contract does not type yet. */
export function apiSend<T>(url: string, method: "POST" | "PUT", body?: unknown): Promise<Envelope<T>> {
  return request<T>(url, method, body ?? {});
}

/** A multipart upload to a route the contract does not type yet. */
export function apiUpload<T>(url: string, form: FormData): Promise<Envelope<T>> {
  return multipart<T>(url, form);
}

/** A browser download of a file the API serves (a package artifact, the client-data template, a stored figure): the
 *  file, or the readable reason it could not be fetched. */
export async function apiFile(url: string): Promise<{ file: Blob | null; problem: string | null }> {
  let res: Response;
  try {
    res = await fetch(url, { headers: { Authorization: `Bearer ${BROWSER_TOKEN}` }, cache: "no-store" });
  } catch {
    return { file: null, problem: UNREACHABLE };
  }
  if (!res.ok) return { file: null, problem: await failure(res) };
  return { file: await res.blob(), problem: null };
}

/** A typed write to a route that answers without the envelope (a signature, a campaign start, an escalation
 *  decision): the answer is wrapped in an envelope here, so it reads and composes (`useMutation`) like every other call. */
export async function post<R extends RouteFor<"post">>(route: R, params: Params<R>, body: Body<R, "post">):
    Promise<Envelope<Answer<R, "post">>> {
  let res: Response;
  try {
    res = await fetch(path(route, params), {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${BROWSER_TOKEN}` },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return errorEnvelope(UNREACHABLE);
  }
  if (!res.ok) return errorEnvelope(await failure(res));
  return { data: (await res.json()) as Answer<R, "post">, meta: { request_id: "", timestamp: "", api_version: "" }, errors: [] };
}
