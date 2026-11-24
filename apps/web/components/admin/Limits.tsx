"use client";

// The monthly limits (docs/plans/2026-11-10-admin-console.md, E; the owner's answer 2): a spend and a token limit per
// company, project or person, each with this month's use. A limit warns the administrator at 80 % and when reached;
// it never stops an agent. Paid models alone also have a hard cap, per run and per month, which pauses the Data room's
// run (plan 2026-11-24 §2.4, the owner's decision D3). Each change needs a reason and a fresh step-up (the API asks; the
// browser's session confirms the person and sends the change once more).

import { useState } from "react";

import { LimitLevel } from "@/components/admin/AdminParts";
import { Panel } from "@/components/kit/Panel";
import { send, type Schema } from "@/lib/api";
import { percent, tokens, usd, when, type PricedAs } from "@/lib/admin";

type Page = Schema<"LimitsPage">;
type Scope = "company" | "project" | "person";

const SCOPES: { id: Scope; label: string }[] = [
  { id: "company", label: "A company" }, { id: "project", label: "A project" }, { id: "person", label: "A person" },
];

const number = (text: string, whole = false) => (text.trim() === "" ? null : whole ? Math.round(Number(text)) : Number(text));

/** The hard cap on paid models only (plan 2026-11-24 §2.4; the owner's decision D3): a run's and a month's spend. Reaching
 *  one pauses the Data room's run; raising it here resumes the runs it paused. */
function PaidCap({ page, onSaved, priced }: { page: Page; onSaved: (next: Page) => void; priced: PricedAs }) {
  const paid = page.paid;
  const [run, setRun] = useState(String(paid.run_usd));
  const [month, setMonth] = useState(String(paid.month_usd));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const valid = Number(run) > 0 && Number(month) > 0 && Number(run) <= Number(month) && Boolean(reason.trim());

  async function save() {
    setBusy(true);
    setProblem(null);
    const env = await send("put", "/api/v1/admin/limits/paid", {}, { run_usd: Number(run), month_usd: Number(month), reason: reason.trim() },
                           { priced_as: priced });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setReason("");
    onSaved(env.data);
  }

  return (
    <Panel title="Paid models: a hard cap">
      <p className="muted">
        For {paid.providers.join(" and ")} only: reaching a cap <strong>pauses</strong> the Data room&apos;s run, which goes on
        where it stopped once the cap is raised or the agent is switched to a free model. Free and in-house models keep the
        warn-only limits above. This month: {usd(paid.month_spent_usd)} of {usd(paid.month_usd)} spent on paid models
        {paid.paused_runs ? `; ${paid.paused_runs} ${paid.paused_runs === 1 ? "run is" : "runs are"} paused by the cap` : ""}.
      </p>
      <form className="admin-filter" onSubmit={(e) => { e.preventDefault(); void save(); }} data-testid="paid-cap-form">
        <label>A run (USD)<input inputMode="decimal" value={run} onChange={(e) => setRun(e.target.value)} data-testid="paid-cap-run" /></label>
        <label>A month (USD)<input inputMode="decimal" value={month} onChange={(e) => setMonth(e.target.value)} data-testid="paid-cap-month" /></label>
        <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="kept with the change"
                         data-testid="paid-cap-reason" /></label>
        <button type="submit" className="btn primary" disabled={busy || !valid} data-testid="paid-cap-save">Change the cap</button>
      </form>
      {problem && <div className="banner err mt-10" data-testid="paid-cap-problem">{problem}</div>}
      <p className="muted mb-0" data-testid="paid-cap-set">
        {paid.set_by ? <>Set {when(paid.set_at)} by {paid.set_by}: {paid.reason}</> : <>The defaults: {paid.reason}.</>}
      </p>
    </Panel>
  );
}

export function Limits({ initial, priced }: { initial: Page; priced: PricedAs }) {
  const [page, setPage] = useState(initial);
  const [scope, setScope] = useState<Scope>("company");
  const [tenant, setTenant] = useState(initial.targets[0]?.tenant_id ?? "");
  const [subject, setSubject] = useState("");
  const [spend, setSpend] = useState("");
  const [cap, setCap] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const target = page.targets.find((t) => t.tenant_id === tenant);
  const subjects = scope === "project" ? (target?.projects ?? []).map((p) => ({ id: p.id, name: p.name }))
    : scope === "person" ? (target?.people ?? []).map((p) => ({ id: p.subject, name: p.name })) : [];
  const id = scope === "company" ? `company:${tenant}` : `${scope}:${tenant}/${subject}`;
  const existing = page.limits.find((l) => l.id === id);
  const ready = Boolean(tenant) && (scope === "company" || Boolean(subject)) && Boolean(reason.trim());
  const valid = [spend, cap].every((v) => v.trim() === "" || Number(v) > 0) && (spend.trim() !== "" || cap.trim() !== "");

  async function save(remove: boolean) {
    setBusy(true);
    setProblem(null);
    const env = await send("put", "/api/v1/admin/limits", {}, {
      scope, tenant_id: tenant, subject: scope === "company" ? "" : subject,
      usd: remove ? null : number(spend), tokens: remove ? null : number(cap, true), reason: reason.trim(),
    }, { priced_as: priced });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setReason("");
    setPage(env.data);
  }

  function edit(row: Page["limits"][number]) {
    setScope(row.scope as Scope);
    setTenant(row.tenant_id);
    setSubject(row.subject);
    setSpend(row.usd === null ? "" : String(row.usd));
    setCap(row.tokens === null ? "" : String(row.tokens));
  }

  return (
    <>
      <Panel title={`This month (${page.month})`}>
        {page.limits.length === 0 ? <p className="muted">No limit set.</p> : (
          <div className="table-scroll">
            <table data-testid="admin-limits">
              <thead>
                <tr><th>Applies to</th><th className="num">Spend</th><th className="num">Tokens</th><th>Level</th>
                  <th>Last change</th><th /></tr>
              </thead>
              <tbody>
                {page.limits.map((l) => (
                  <tr key={l.id} data-testid={`limit-${l.id}`}>
                    <td>{l.label}<div className="muted">{l.scope}</div></td>
                    <td className="num">{l.usd === null ? "—" : <>{usd(l.used_usd)} of {usd(l.usd)}<div className="muted">{percent(l.usd_share)}</div></>}</td>
                    <td className="num">{l.tokens === null ? "—" : <>{tokens(l.used_tokens)} of {tokens(l.tokens)}<div className="muted">{percent(l.tokens_share)}</div></>}</td>
                    <td><LimitLevel row={l} /></td>
                    <td>{when(l.set_at)}<div className="muted">{l.reason} ({l.set_by})</div></td>
                    <td><button type="button" className="btn" onClick={() => edit(l)} data-testid={`limit-edit-${l.id}`}>Change</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted mb-0">
          Spend is estimated as on the usage page: each run&apos;s tokens at the chosen Claude model&apos;s list prices, cached.
          Tokens are those in and out. A month is a calendar month (UTC).
        </p>
      </Panel>
      <PaidCap page={page} onSaved={setPage} priced={priced} />
      <Panel title="Set a limit">
        <form className="admin-filter" onSubmit={(e) => { e.preventDefault(); void save(false); }} data-testid="limit-form">
          <label>On
            <select value={scope} onChange={(e) => { setScope(e.target.value as Scope); setSubject(""); }} data-testid="limit-scope">
              {SCOPES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </label>
          <label>Company
            <select value={tenant} onChange={(e) => { setTenant(e.target.value); setSubject(""); }} data-testid="limit-tenant">
              {page.targets.map((t) => <option key={t.tenant_id} value={t.tenant_id}>{t.tenant_id}</option>)}
            </select>
          </label>
          {scope !== "company" && (
            <label>{scope === "project" ? "Project" : "Person"}
              <select value={subject} onChange={(e) => setSubject(e.target.value)} data-testid="limit-subject">
                <option value="">choose</option>
                {subjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
          )}
          <label>Spend a month (USD)<input inputMode="decimal" value={spend} onChange={(e) => setSpend(e.target.value)}
                                           placeholder="none" data-testid="limit-usd" /></label>
          <label>Tokens a month<input inputMode="numeric" value={cap} onChange={(e) => setCap(e.target.value)}
                                      placeholder="none" data-testid="limit-tokens" /></label>
          <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="kept with the change"
                           data-testid="limit-reason" /></label>
          <button type="submit" className="btn primary" disabled={busy || !ready || !valid} data-testid="limit-save">
            {existing ? "Change the limit" : "Set the limit"}
          </button>
          {existing && (
            <button type="button" className="btn" disabled={busy || !ready} onClick={() => void save(true)} data-testid="limit-remove">
              Remove it
            </button>
          )}
        </form>
        {problem && <div className="banner err mt-10" data-testid="limit-problem">{problem}</div>}
      </Panel>
      <Panel title="Changes">
        {page.history.length === 0 ? <p className="muted">No change yet.</p> : (
          <ul className="plain-list" data-testid="limit-history">
            {page.history.map((h) => (
              <li key={`${h.id}-${h.at}`}>
                {when(h.at)} · <strong>{h.id}</strong> →{" "}
                {h.usd === null && h.tokens === null ? "removed"
                  : [h.usd !== null && `${usd(h.usd)} spend`, h.tokens !== null && `${tokens(h.tokens)} tokens`].filter(Boolean).join(", ")}
                {" "}· {h.reason}<span className="muted"> ({h.by})</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}
