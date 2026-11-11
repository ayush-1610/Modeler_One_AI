"use client";

// Each agent's model, chosen in the console (docs/plans/2026-11-10-admin-console.md, C). A change needs a reason and a
// fresh step-up (the API asks for it; the browser's session confirms the person and sends the change once more).

import { useState } from "react";

import { Card } from "@/components/ui";
import { send, type Schema } from "@/lib/api";
import { when } from "@/lib/admin";

type Page = Schema<"AgentsPage">;
type Row = Page["agents"][number];

function RunsOn({ row }: { row: Row }) {
  const r = row.runs_on;
  return r.enabled
    ? <span className="chip low" data-testid={`runs-on-${row.agent}`}><span className="chip-dot" />{r.provider} · {r.model}</span>
    : <span className="chip high" data-testid={`runs-on-${row.agent}`} title={r.problem ?? ""}>
        <span className="chip-dot" />{r.problem ?? "no model"}
      </span>;
}

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
  const changed = provider !== row.provider || (needsModel && model.trim() !== row.model)
    || (claude && (effort !== row.effort || fallback !== row.fallback));

  async function save() {
    setBusy(true);
    setProblem(null);
    const env = await send("put", "/api/v1/admin/agents/{agent}", { agent: row.agent },
                           { provider, model: needsModel ? model.trim() : "", effort: claude ? effort : "",
                             fallback: claude ? fallback : "", reason: reason.trim() });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setReason("");
    onSaved(env.data);
  }

  return (
    <div className="admin-filter" data-testid={`agent-editor-${row.agent}`}>
      <label>Provider
        <select value={provider} onChange={(e) => setProvider(e.target.value)} data-testid={`agent-provider-${row.agent}`}>
          {page.providers.map((p) => (
            <option key={p.id} value={p.id}>{p.label}{p.needs_model && !p.has_active_key ? " (no active key)" : ""}</option>
          ))}
        </select>
      </label>
      {needsModel && (
        <label>Model<input value={model} onChange={(e) => setModel(e.target.value)}
                           placeholder={claude ? page.claude_models[0] : "qwen-coder"} list={claude ? "claude-models" : undefined}
                           data-testid={`agent-model-${row.agent}`} /></label>
      )}
      {claude && (
        <>
          <label>Effort
            <select value={effort} onChange={(e) => setEffort(e.target.value)} data-testid={`agent-effort-${row.agent}`}>
              <option value="">the model&apos;s default</option>
              {page.efforts.map((e) => <option key={e} value={e}>{e}</option>)}
            </select>
          </label>
          <label>Fallback model
            <select value={fallback} onChange={(e) => setFallback(e.target.value)} data-testid={`agent-fallback-${row.agent}`}>
              <option value="">none</option>
              {page.claude_models.filter((m) => m !== model.trim()).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
        </>
      )}
      <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="the reason, kept with the change"
                       data-testid={`agent-reason-${row.agent}`} /></label>
      <button type="button" className="btn primary" disabled={busy || !changed || !reason.trim() || (needsModel && !model.trim())}
              onClick={() => void save()} data-testid={`agent-save-${row.agent}`}>Save</button>
      {problem && <span className="banner err" data-testid={`agent-problem-${row.agent}`}>{problem}</span>}
    </div>
  );
}

export function AgentModels({ initial }: { initial: Page }) {
  const [page, setPage] = useState(initial);
  const env = page.environment;
  return (
    <>
      <datalist id="claude-models">{page.claude_models.map((m) => <option key={m} value={m} />)}</datalist>
      <Card title="Each agent's model">
        <p className="muted mt-0">
          An agent left &ldquo;as the server&apos;s environment says&rdquo; runs on{" "}
          <strong>{env.enabled ? `${env.provider} · ${env.model}` : "nothing (agents off)"}</strong>. A provider chosen
          here uses its active key (Keys). The next run takes the change; nothing restarts. On Claude, effort sets how
          much the model thinks (and so its cost and speed); the fallback model answers when the first declines a request
          or stays overloaded.
        </p>
        <div className="table-scroll">
          <table data-testid="admin-agents">
            <thead><tr><th>Agent</th><th>Set to</th><th>Runs on now</th><th>Last change</th></tr></thead>
            <tbody>
              {page.agents.map((a) => (
                <tr key={a.agent}>
                  <td>{a.label}<AgentEditor row={a} page={page} onSaved={setPage} /></td>
                  <td>
                    {a.provider_label}{a.model ? <div className="muted"><code>{a.model}</code></div> : null}
                    {a.effort ? <div className="muted">effort {a.effort}</div> : null}
                    {a.fallback ? <div className="muted">fallback <code>{a.fallback}</code></div> : null}
                  </td>
                  <td><RunsOn row={a} /></td>
                  <td>{a.set_at ? <>{when(a.set_at)}<div className="muted">{a.reason}</div></> : <span className="muted">never</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Changes">
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
      </Card>
    </>
  );
}
