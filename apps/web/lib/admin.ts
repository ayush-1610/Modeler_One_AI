// The platform owner's console (docs/plans/2026-11-10-admin-console.md): server reads of /api/v1/admin/*. The API
// answers only the realm role modeler-admin; anyone else gets its 403, shown as "only the platform's owner".

import { serverGet, type Schema } from "@/lib/api";

export type Usage = Schema<"Usage">;
export type UsageGroup = Schema<"UsageGroup">;
export type PricedAs = "claude-opus-5-5" | "claude-sonnet-5-5" | "claude-haiku-5-5";
export const PRICED_AS: { id: PricedAs; label: string }[] = [
  { id: "claude-opus-5-5", label: "Claude Opus 5.5" },
  { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
  { id: "claude-haiku-5-5", label: "Claude Haiku 5.5" },
];

export function pricedAs(value: string | undefined): PricedAs {
  return PRICED_AS.find((p) => p.id === value)?.id ?? "claude-opus-5-5";
}

export const getOverview = (priced: PricedAs) => serverGet("/api/v1/admin/overview", {}, { priced_as: priced });
export const getCompany = (tenantId: string, priced: PricedAs) =>
  serverGet("/api/v1/admin/companies/{tenant_id}", { tenant_id: tenantId }, { priced_as: priced });
export const getUsage = (query: { since?: string; tenant_id?: string; priced_as: PricedAs }) =>
  serverGet("/api/v1/admin/usage", {}, query);
export const getAgents = () => serverGet("/api/v1/admin/agents", {});
export const getKeys = () => serverGet("/api/v1/admin/keys", {});

/** The API refused: this person is not the platform's owner (403), as against a problem reaching it. */
export function refused(problem: string | null): boolean {
  return Boolean(problem?.includes("HTTP 403"));
}

export const tokens = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(2)} M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)} k` : String(n));
export const usd = (n: number) => (n > 0 && n < 0.01 ? "< $0.01" : `$${n.toFixed(2)}`);
export const when = (iso: string | null) => (iso ? iso.slice(0, 16).replace("T", " ") : "—");
