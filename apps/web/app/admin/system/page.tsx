// System status (the redesign's P-32; the owner, 2026-11-24: the pages we are missing, and checking the AI keys end to
// end): whether the API answers and how it signs people in, whether the server's master key opens the stored keys, each
// AI service's active key and its last test, and what each agent runs on now. Reads only: every change is on Keys and
// Models. The engine's own check needs a new route (R-N08) and is not shown yet.

import Link from "next/link";

import { AdminTabs } from "@/components/admin/AdminParts";
import { Hero } from "@/components/kit";
import { ApiProblem } from "@/components/ui";
import { getAgents, getKeys, getOverview, hideUnlessAdmin } from "@/lib/admin";
import { oidcConfig } from "@/lib/oidc";

export const metadata = { title: "System status · Modeler One" };

const AI_SERVICES = ["litellm", "groq", "nvidia", "bedrock", "anthropic", "openai_compat"];

function State({ ok, children, testId }: { ok: boolean | null; children: React.ReactNode; testId?: string }) {
  const word = ok === null ? "Not set" : ok ? "OK" : "Needs attention";
  return <span className={`status-chip ${ok === null ? "muted" : ok ? "ok" : "warn"}`} data-testid={testId}>{word}: {children}</span>;
}

export default async function SystemPage() {
  const [overview, keys, agents] = await Promise.all([getOverview("claude-opus-5-5"), getKeys(), getAgents()]);
  const oidc = oidcConfig();
  hideUnlessAdmin(overview.problem);
  const k = keys.data;
  const active = (provider: string) => k?.keys.find((x) => x.provider === provider && x.state === "active") ?? null;
  return (
    <main data-testid="system-page">
      <Hero tone="admin" eyebrow="Admin console" title="System status"
            lede="Whether each part of the platform answers, and what the agents run on now. Changes are made on Keys and Models." />
      <AdminTabs here="system" />
      {[overview.problem, keys.problem, agents.problem].filter(Boolean).map((p) => <ApiProblem key={p} problem={p!} />)}
      <div className="account-grid">
        <section className="card" aria-labelledby="sys-platform">
          <h2 id="sys-platform">Platform</h2>
          <dl className="account-facts">
            <dt>API</dt><dd><State ok={Boolean(overview.data)} testId="sys-api">{overview.data ? "answers" : "no answer"}</State></dd>
            <dt>Deployment</dt><dd>{overview.data?.system.deployment ?? "—"}</dd>
            <dt>Sign-in</dt>
            <dd data-testid="sys-signin">{oidc ? `Keycloak (named people, Part 11): ${oidc.issuer}` : "Development sign-in (one user, not Part 11)"}</dd>
            <dt>Project store</dt><dd><State ok={overview.data?.system.store ?? null}>{overview.data?.system.store ? "readable" : "not set"}</State></dd>
            <dt>Master key</dt>
            <dd data-testid="sys-master"><State ok={k ? k.master_key && !k.master_problem : null}>
              {k?.master_problem ?? (k?.master_key ? "opens the stored keys" : "MODELER_MASTER_KEY is not set (Help → AI model keys, step 1)")}
            </State></dd>
          </dl>
        </section>
        <section className="card" aria-labelledby="sys-keys">
          <h2 id="sys-keys">AI services and their keys</h2>
          <table className="table-compact" data-testid="sys-keys-table">
            <thead><tr><th>Service</th><th>Active key</th><th>Last test</th></tr></thead>
            <tbody>
              {(k?.providers ?? []).filter((p) => AI_SERVICES.includes(p.id)).map((p) => {
                const key = active(p.id);
                return (
                  <tr key={p.id} data-testid={`sys-key-${p.id}`}>
                    <td>{p.label}</td>
                    <td>{key ? `…${Object.values(key.last4)[0] ?? ""} (since ${(key.activated_at ?? key.added_at).slice(0, 10)})` : "none"}</td>
                    <td>{key?.tested_at
                      ? <State ok={key.test_ok ?? false}>{key.test_message ?? ""} ({key.tested_at.slice(0, 10)})</State>
                      : key ? "not tested" : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="muted">Add, test and activate keys on <Link href="/admin/keys">Keys</Link>; the steps are in{" "}
            <Link href="/help#6b-ai-model-keys-end-to-end-the-server-groqcloud-nvidia-the-claude-api">Help → AI model keys</Link>.</p>
        </section>
        <section className="card" aria-labelledby="sys-agents">
          <h2 id="sys-agents">What the agents run on now</h2>
          <table className="table-compact" data-testid="sys-agents-table">
            <thead><tr><th>Agent</th><th>Runs on</th></tr></thead>
            <tbody>
              {(agents.data?.agents ?? []).map((a) => (
                <tr key={a.agent}>
                  <td>{a.label}</td>
                  <td>{a.runs_on.enabled
                    ? <>{a.runs_on.provider}/{a.runs_on.model}{a.runs_on.then?.length ? <>, then {a.runs_on.then.join(", ")}</> : null}</>
                    : <State ok={false}>{a.runs_on.problem ?? "no model"}</State>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">A project's client files go only to the services its owner allowed (Data room → Where the files
            may go); the in-house model needs no permission.</p>
        </section>
      </div>
    </main>
  );
}
