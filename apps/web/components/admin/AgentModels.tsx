"use client";

// Each agent's model, chosen in the console (docs/plans/2026-11-10-admin-console.md, C). A change needs a reason and a
// fresh step-up (the API asks for it; the browser's session confirms the person and sends the change once more).
// Each agent's row offers three one-click models (plan 2026-11-21 v2 §9): Qwen Coder, Claude and gpt-oss-120b on
// GroqCloud; a click is kept with the reason "one-click switch" and who made it. "More…" keeps the detailed form for any
// other choice (a model name, an effort, a fallback).

import Link from "next/link";
import { useState } from "react";

import { Panel } from "@/components/kit/Panel";
import { send, type Schema } from "@/lib/api";
import { when } from "@/lib/admin";

type Page = Schema<"AgentsPage">;
type Row = Page["agents"][number];
type Choice = Page["choices"][number];

/** The reason a one-click change is kept with (the API records who made it). */
const ONE_CLICK = "one-click switch";

function RunsOn({ row }: { row: Row }) {
  const r = row.runs_on;
  return r.enabled
    ? <span className="chip low" data-testid={`runs-on-${row.agent}`}><span className="chip-dot" />{r.provider} · {r.model}
        {(r.then ?? []).length > 0 && <span className="muted"> · then {(r.then ?? []).join(", ")}</span>}</span>
    : <span className="chip high" data-testid={`runs-on-${row.agent}`} title={r.problem ?? ""}>
        <span className="chip-dot" />{r.problem ?? "no model"}
      </span>;
}

/** The efforts a provider takes: Claude's own, GroqCloud's (low, medium, high), none for the others. */
function effortsFor(page: Page, provider: string): string[] {
  return provider === "bedrock" ? page.efforts : provider === "groq" ? page.groq_efforts : [];
}

/** A provider's one-click model and effort, the form's starting point when the provider is changed in it. */
function defaultsFor(page: Page, provider: string): { model: string; effort: string } {
  const c = page.choices.find((x) => x.provider === provider);
  return { model: c?.model ?? "", effort: c?.effort ?? "" };
}

/** What a model can do, in small marks: every one calls tools; only Claude reads a scanned page itself. */
function Capabilities({ choice }: { choice: Choice }) {
  return (
    <span className="model-caps">
      <span className="cap-yes">tools ✓</span>
      {choice.reads_scans
        ? <span className="cap-yes">reads scans ✓</span>
        : <span title="Reads text only: a scanned page reaches it as the OCR's text">text only</span>}
    </span>
  );
}

/** The three one-click models on an agent's row. The active one is marked; one whose provider has no active key is
 *  disabled and says where to add one. */
function OneClick({ row, page, onSaved }: { row: Row; page: Page; onSaved: (p: Page) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function pick(c: Choice) {
    if (c.id === row.choice) return;
    setBusy(c.id);
    setProblem(null);
    const env = await send("put", "/api/v1/admin/agents/{agent}", { agent: row.agent },
                           { provider: c.provider, model: c.model, effort: c.effort, fallback: "", reason: ONE_CLICK });
    setBusy(null);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    onSaved(env.data);
  }

  return (
    <>
      <div className="model-pick" role="group" aria-label={`Model for ${row.label}`} data-testid={`agent-choices-${row.agent}`}>
        {page.choices.map((c) => {
          const on = c.id === row.choice;
          return (
            <button key={c.id} type="button" className={`model-choice${on ? " on" : ""}`} aria-pressed={on}
                    disabled={!c.has_active_key || busy !== null} onClick={() => void pick(c)}
                    title={c.has_active_key ? `${c.model}${c.effort ? `, effort ${c.effort}` : ""}` : "Add a key under Keys"}
                    data-testid={`agent-choice-${row.agent}-${c.id}`}>
              <span className="model-choice-name">
                {c.label}{on && <span className="model-choice-on"> · in use</span>}
                {busy === c.id && <span className="model-choice-on"> · switching…</span>}
              </span>
              <Capabilities choice={c} />
              {!c.has_active_key && <span className="model-choice-note">Add a key under Keys</span>}
            </button>
          );
        })}
      </div>
      {problem && <span className="banner err" data-testid={`agent-choice-problem-${row.agent}`}>{problem}</span>}
    </>
  );
}

/** The detailed form behind "More…": any provider, a model name, an effort and (on Claude) a fallback, with a reason. */
function AgentEditor({ row, page, onSaved }: { row: Row; page: Page; onSaved: (p: Page) => void }) {
  const [provider, setProvider] = useState(row.provider);
  const [model, setModel] = useState(row.model);
  const [effort, setEffort] = useState(row.effort);
  const [fallback, setFallback] = useState(row.fallback);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const needsModel = page.providers.find((p) => p.id === provider)?.needs_model ?? false;
  const claude = provider === "bedrock";
  const efforts = effortsFor(page, provider);
  const changed = provider !== row.provider || (needsModel && model.trim() !== row.model)
    || (efforts.length > 0 && effort !== row.effort) || (claude && fallback !== row.fallback);

  function changeProvider(next: string) {
    setProvider(next);
    const d = next === row.provider ? { model: row.model, effort: row.effort } : defaultsFor(page, next);
    setModel(d.model);
    setEffort(d.effort);
    setFallback(next === row.provider ? row.fallback : "");
  }

  async function save() {
    setBusy(true);
    setProblem(null);
    const env = await send("put", "/api/v1/admin/agents/{agent}", { agent: row.agent },
                           { provider, model: needsModel ? model.trim() : "", effort: efforts.length ? effort : "",
                             fallback: claude ? fallback : "", reason: reason.trim() });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setReason("");
    onSaved(env.data);
  }

  return (
    <div className="admin-filter" data-testid={`agent-editor-${row.agent}`}>
      <label>Provider
        <select value={provider} onChange={(e) => changeProvider(e.target.value)} data-testid={`agent-provider-${row.agent}`}>
          {page.providers.map((p) => (
            <option key={p.id} value={p.id}>{p.label}{p.needs_model && !p.has_active_key ? " (no active key)" : ""}</option>
          ))}
        </select>
      </label>
      {needsModel && (
        <label>Model<input value={model} onChange={(e) => setModel(e.target.value)}
                           placeholder={defaultsFor(page, provider).model || "the model's name"}
                           list={claude ? "claude-models" : undefined} data-testid={`agent-model-${row.agent}`} /></label>
      )}
      {efforts.length > 0 && (
        <label>Effort
          <select value={effort} onChange={(e) => setEffort(e.target.value)} data-testid={`agent-effort-${row.agent}`}>
            <option value="">the model&apos;s default</option>
            {efforts.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
        </label>
      )}
      {claude && (
        <label>Fallback model
          <select value={fallback} onChange={(e) => setFallback(e.target.value)} data-testid={`agent-fallback-${row.agent}`}>
            <option value="">none</option>
            {page.claude_models.filter((m) => m !== model.trim()).map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
      )}
      <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="the reason, kept with the change"
                       data-testid={`agent-reason-${row.agent}`} /></label>
      <button type="button" className="btn primary" disabled={busy || !changed || !reason.trim() || (needsModel && !model.trim())}
              onClick={() => void save()} data-testid={`agent-save-${row.agent}`}>Save</button>
      {problem && <span className="banner err" data-testid={`agent-problem-${row.agent}`}>{problem}</span>}
    </div>
  );
}

/** Every agent onto one provider in one step (the owner, 2026-11-11): Claude on Bedrock, or back to the in-house model
 *  when Bedrock is lost. A provider whose key is not active is refused by the API, and offered here only once it is. */
function SwitchEveryAgent({ page, onSaved }: { page: Page; onSaved: (p: Page) => void }) {
  const [provider, setProvider] = useState("environment");
  const [model, setModel] = useState(page.claude_models[0] ?? "");
  const [effort, setEffort] = useState("");
  const [fallback, setFallback] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const chosen = page.providers.find((p) => p.id === provider);
  const needsModel = chosen?.needs_model ?? false;
  const claude = provider === "bedrock";
  const efforts = effortsFor(page, provider);
  const usable = !needsModel || Boolean(chosen?.has_active_key);
  const now = [...new Set(page.agents.map((a) => (a.runs_on.enabled ? `${a.runs_on.provider} · ${a.runs_on.model}` : "off")))];

  function changeProvider(next: string) {
    setProvider(next);
    const d = defaultsFor(page, next);
    setModel(d.model);
    setEffort(d.effort);
    setFallback("");
  }

  async function save() {
    setBusy(true);
    setProblem(null);
    setDone(null);
    const env = await send("put", "/api/v1/admin/agents", {},
                           { provider, model: needsModel ? model.trim() : "", effort: efforts.length ? effort : "",
                             fallback: claude ? fallback : "", reason: reason.trim() });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setReason("");
    setDone(`Every agent now: ${chosen?.label ?? provider}${needsModel ? ` · ${model.trim()}` : ""}. The next run of each takes it.`);
    onSaved(env.data);
  }

  return (
    <Panel title="Switch every agent">
      <p className="muted" style={{ marginTop: 0 }}>
        Puts all {page.agents.length} agents on one model at once, for example back on the in-house model (&ldquo;as the
        server&apos;s environment says&rdquo;) if Claude on Bedrock stops answering, and onto Claude again later. Running
        now on: <strong data-testid="agents-now">{now.join(", ")}</strong>.
      </p>
      <form className="admin-filter" onSubmit={(e) => { e.preventDefault(); void save(); }} data-testid="switch-every-agent">
        <label>Provider
          <select value={provider} onChange={(e) => changeProvider(e.target.value)} data-testid="switch-provider">
            {page.providers.map((p) => (
              <option key={p.id} value={p.id}>{p.label}{p.needs_model && !p.has_active_key ? " (no active key: add one under Keys)" : ""}</option>
            ))}
          </select>
        </label>
        {needsModel && (
          <label>Model<input value={model} onChange={(e) => setModel(e.target.value)} list={claude ? "claude-models" : undefined}
                             placeholder={defaultsFor(page, provider).model || "the model's name"} data-testid="switch-model" /></label>
        )}
        {efforts.length > 0 && (
          <label>Effort
            <select value={effort} onChange={(e) => setEffort(e.target.value)} data-testid="switch-effort">
              <option value="">the model&apos;s default</option>
              {efforts.map((e) => <option key={e} value={e}>{e}</option>)}
            </select>
          </label>
        )}
        {claude && (
          <label>Fallback model
            <select value={fallback} onChange={(e) => setFallback(e.target.value)} data-testid="switch-fallback">
              <option value="">none</option>
              {page.claude_models.filter((m) => m !== model.trim()).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
        )}
        <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="kept with each agent's change"
                         data-testid="switch-reason" /></label>
        <button type="submit" className="btn primary" data-testid="switch-submit"
                disabled={busy || !usable || !reason.trim() || (needsModel && !model.trim())}>Switch every agent</button>
      </form>
      {problem && <div className="banner err" style={{ marginTop: 10 }} data-testid="switch-problem">{problem}</div>}
      {done && <div className="banner ok" style={{ marginTop: 10 }} data-testid="switch-done">{done}</div>}
    </Panel>
  );
}

/** What every agent goes on with when its own model cannot answer (the owner, 2026-11-22: "switch at that moment to
 *  another, so the task continues"): an ordered list of the one-click models, each with what its service does with the
 *  files it is sent. Saving needs a reason and the step-up: a cloud model here receives client files. */
function FailoverChain({ page, onSaved }: { page: Page; onSaved: (p: Page) => void }) {
  const [order, setOrder] = useState<string[]>(page.chain.choices);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const byId = new Map(page.choices.map((c) => [c.id, c]));
  const left = page.choices.filter((c) => !order.includes(c.id));
  const changed = order.join("|") !== page.chain.choices.join("|");

  function move(i: number, by: number) {
    const next = [...order];
    const [x] = next.splice(i, 1);
    next.splice(i + by, 0, x);
    setOrder(next);
  }

  async function save() {
    setBusy(true);
    setProblem(null);
    const env = await send("put", "/api/v1/admin/agent-chain", {}, { choices: order, reason });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setReason("");
    onSaved(env.data);
  }

  return (
    <Panel title="When a model cannot answer">
      <p className="muted mt-0" data-testid="chain-notice">{page.chain.notice}</p>
      {order.length === 0
        ? <p data-testid="chain-empty">No model is listed: an agent whose model cannot answer stops and says why.</p>
        : (
          <ol className="chain-list" data-testid="chain-list">
            {order.map((id, i) => {
              const c = byId.get(id);
              return (
                <li key={id} data-testid={`chain-${id}`}>
                  <strong>{c?.label ?? id}</strong>
                  {c && !c.has_active_key && <span className="chip high"><span className="chip-dot" />no active key: skipped</span>}
                  <div className="muted">{c?.terms}</div>
                  <span className="chain-moves">
                    <button type="button" className="btn small" disabled={i === 0} onClick={() => move(i, -1)}
                            aria-label={`Move ${c?.label ?? id} up`}>↑</button>
                    <button type="button" className="btn small" disabled={i === order.length - 1} onClick={() => move(i, 1)}
                            aria-label={`Move ${c?.label ?? id} down`}>↓</button>
                    <button type="button" className="btn small" onClick={() => setOrder(order.filter((x) => x !== id))}
                            aria-label={`Take ${c?.label ?? id} out`}>Take out</button>
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      {left.length > 0 && (
        <div className="chain-add" role="group" aria-label="Add a model to the list">
          {left.map((c) => (
            <button key={c.id} type="button" className="btn small" data-testid={`chain-add-${c.id}`}
                    onClick={() => setOrder([...order, c.id])} title={c.terms}>+ {c.label}</button>
          ))}
        </div>
      )}
      <div className="chain-save">
        <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} data-testid="chain-reason"
                         placeholder="kept with the change" /></label>
        <button type="button" className="btn primary" disabled={busy || !changed || !reason.trim()} onClick={() => void save()}
                data-testid="chain-save">Save the list</button>
      </div>
      {page.chain.set_at && (
        <p className="muted" data-testid="chain-last">Last set {when(page.chain.set_at)}: {page.chain.reason}
          {page.chain.set_by ? ` (${page.chain.set_by})` : ""}</p>
      )}
      {problem && <div className="banner err" style={{ marginTop: 10 }} data-testid="chain-problem">{problem}</div>}
    </Panel>
  );
}

export function AgentModels({ initial }: { initial: Page }) {
  const [page, setPage] = useState(initial);
  const env = page.environment;
  return (
    <>
      <datalist id="claude-models">{page.claude_models.map((m) => <option key={m} value={m} />)}</datalist>
      <SwitchEveryAgent page={page} onSaved={setPage} />
      <FailoverChain key={page.chain.set_at ?? "none"} page={page} onSaved={setPage} />
      <Panel title="Each agent's model">
        <p className="muted mt-0">
          One click puts an agent on Qwen Coder (the in-house model), Claude, gpt-oss-120b (on GroqCloud) or Nemotron
          Ultra (NVIDIA&apos;s API catalog); the change
          is kept with who made it. Each uses its provider&apos;s active key (<Link href="/admin/keys">Keys</Link>), and the
          next run takes it: nothing
          restarts. Every one calls tools; only Claude reads a scanned page itself (the others read its OCR text).
          &ldquo;More…&rdquo; sets any other model, its effort (how much the model thinks, and so its cost and speed) or,
          on Claude, a fallback model. An agent left &ldquo;as the server&apos;s environment says&rdquo; runs on{" "}
          <strong>{env.enabled ? `${env.provider} · ${env.model}` : "nothing (agents off)"}</strong>.
        </p>
        <div className="table-scroll">
          <table data-testid="admin-agents">
            <thead><tr><th>Agent</th><th>Set to</th><th>Runs on now</th><th>Last change</th></tr></thead>
            <tbody>
              {page.agents.map((a) => (
                <tr key={a.agent} data-testid={`agent-row-${a.agent}`}>
                  <td className="agent-cell">
                    <strong>{a.label}</strong>
                    <OneClick row={a} page={page} onSaved={setPage} />
                    <details className="model-more">
                      <summary data-testid={`agent-more-${a.agent}`}>More…</summary>
                      {/* keyed by the setting, so the form starts again from it after a one-click change */}
                      <AgentEditor key={`${a.provider}|${a.model}|${a.effort}|${a.fallback}|${a.set_at ?? ""}`}
                                   row={a} page={page} onSaved={setPage} />
                    </details>
                  </td>
                  <td>
                    {a.provider_label}{a.model ? <div className="muted"><code>{a.model}</code></div> : null}
                    {a.effort ? <div className="muted">effort {a.effort}</div> : null}
                    {a.fallback ? <div className="muted">fallback <code>{a.fallback}</code></div> : null}
                  </td>
                  <td><RunsOn row={a} /></td>
                  <td>{a.set_at ? <>{when(a.set_at)}<div className="muted">{a.reason}{a.set_by ? ` (${a.set_by})` : ""}</div></>
                                : <span className="muted">never</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Changes">
        {page.history.length === 0 ? <p className="muted">No change yet.</p> : (
          <ul className="plain-list" data-testid="admin-agent-history">
            {page.history.map((h) => (
              <li key={`${h.agent}-${h.at}`}>
                {when(h.at)} · <strong>{h.agent}</strong> → {h.provider}{h.model ? ` · ${h.model}` : ""} · {h.reason}
                <span className="muted"> ({h.by})</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}
