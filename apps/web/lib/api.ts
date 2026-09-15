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

export type QuestionStatus = {
  id: string;
  question: string;
  application: string;
  modelRisk: Rating | null;
  stage: "planning" | "evaluation" | "reporting" | "signed";
  failingCriteria: number;
};
