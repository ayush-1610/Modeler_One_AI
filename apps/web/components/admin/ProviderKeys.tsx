"use client";

// The providers' keys (docs/plans/2026-11-10-admin-console.md, D): added write-only (the browser never reads one
// back), tested, made active (the provider's active key is then retired) and retired. Each change needs a reason and a
// fresh step-up; the list shows a key by its last 4 characters.

import { useState } from "react";

import { Card } from "@/components/ui";
import { send, type Schema } from "@/lib/api";
import { when } from "@/lib/admin";
import { Banner } from "@/components/kit";

type Page = Schema<"KeysPage">;
type Key = Page["keys"][number];

const STATE_CHIP: Record<string, string> = { active: "low", new: "medium", retired: "neutral" };

function AddKey({ page, onDone }: { page: Page; onDone: (p: Page) => void }) {
  const [provider, setProvider] = useState(page.providers[0]?.id ?? "");
  const [label, setLabel] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const spec = page.providers.find((p) => p.id === provider);

  async function add() {
    setBusy(true);
    setProblem(null);
    const env = await send("post", "/api/v1/admin/keys", {}, { provider, label, fields, reason: reason.trim() });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setFields({});                                           // the secret leaves the page once stored
    setLabel("");
    setReason("");
    onDone(env.data);
  }

  return (
    <Card title="Add a key">
      <form className="admin-filter" autoComplete="off" onSubmit={(e) => { e.preventDefault(); void add(); }} data-testid="key-add">
        <label>Provider
          <select value={provider} onChange={(e) => { setProvider(e.target.value); setFields({}); }} data-testid="key-provider">
            {page.providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </label>
        <label>Name<input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Nov 2026 rotation" /></label>
        {spec?.fields.map((f) => (
          <label key={f.name}>{f.label}{f.required ? "" : " (or)"}
            <input type={f.secret ? "password" : "text"} autoComplete={f.secret ? "new-password" : "off"}
                   value={fields[f.name] ?? ""} onChange={(e) => setFields({ ...fields, [f.name]: e.target.value })}
                   data-testid={`key-field-${f.name}`} />
          </label>
        ))}
        <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="kept with the change"
                         data-testid="key-reason" /></label>
        <button type="submit" className="btn primary" disabled={busy || !reason.trim() || !page.master_key} data-testid="key-add-submit">
          Add the key
        </button>
      </form>
      {problem && <Banner tone="err" className="mt-10" testId="key-problem">{problem}</Banner>}
      <p className="muted mb-0">A new key is not used until it is made active. Test it first.</p>
    </Card>
  );
}

function KeyActions({ k, onDone }: { k: Key; onDone: (p: Page) => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function act(action: "test" | "activate" | "retire") {
    setBusy(true);
    setProblem(null);
    const params = { key_id: k.id };
    const env = action === "test"
      ? await send("post", "/api/v1/admin/keys/{key_id}:test", params)
      : action === "activate"
        ? await send("post", "/api/v1/admin/keys/{key_id}:activate", params, { reason: reason.trim() })
        : await send("post", "/api/v1/admin/keys/{key_id}:retire", params, { reason: reason.trim() });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setReason("");
    onDone(env.data);
  }

  if (k.state === "retired") return <span className="muted">retired {when(k.retired_at)}</span>;
  return (
    <div className="admin-filter">
      <button type="button" className="btn" disabled={busy} onClick={() => void act("test")} data-testid={`key-test-${k.id}`}>Test</button>
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="why" aria-label="Why"
             data-testid={`key-why-${k.id}`} />
      {k.state === "new" && (
        <button type="button" className="btn primary" disabled={busy || !reason.trim()} onClick={() => void act("activate")}
                data-testid={`key-activate-${k.id}`}>Make active</button>
      )}
      <button type="button" className="btn" disabled={busy || !reason.trim()} onClick={() => void act("retire")}
              data-testid={`key-retire-${k.id}`}>Retire</button>
      {problem && <span className="banner err" role="alert">{problem}</span>}
    </div>
  );
}

export function ProviderKeys({ initial }: { initial: Page }) {
  const [page, setPage] = useState(initial);
  const label = (id: string) => page.providers.find((p) => p.id === id)?.label ?? id;
  return (
    <>
      {!page.master_key && <Banner tone="err" testId="master-key-missing">{page.master_problem}</Banner>}
      <Card title="Keys">
        {page.keys.length === 0 ? <p className="muted">No key stored yet: the agents use the server&apos;s environment.</p> : (
          <div className="table-scroll">
            <table data-testid="admin-keys">
              <thead><tr><th>Key</th><th>State</th><th>Added</th><th>Last test</th><th>Actions</th></tr></thead>
              <tbody>
                {page.keys.map((k) => (
                  <tr key={k.id}>
                    <td>
                      {label(k.provider)}{k.label !== label(k.provider) ? ` · ${k.label}` : ""}
                      <div className="muted">
                        {Object.entries(k.plain).map(([f, v]) => <span key={f}>{f} {v} · </span>)}
                        {Object.entries(k.last4).map(([f, v]) => <span key={f}>{f} ••••{v} </span>)}
                      </div>
                    </td>
                    <td>
                      <span className={`chip ${STATE_CHIP[k.state] ?? "neutral"}`} data-testid={`key-state-${k.id}`}>{k.state}</span>
                      {k.active_days !== null && <div className="muted">{k.active_days} days active</div>}
                      {k.due && <Banner tone="warn" testId={`key-due-${k.id}`}>Due for rotation ({page.rotate_after_days} days)</Banner>}
                    </td>
                    <td>{when(k.added_at)}<div className="muted">{k.added_by}</div></td>
                    <td>{k.tested_at ? <>{k.test_ok ? "answers" : "failed"} · {when(k.tested_at)}
                      <div className="muted">{k.test_message}</div></> : <span className="muted">not tested</span>}</td>
                    <td><KeyActions k={k} onDone={setPage} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <AddKey page={page} onDone={setPage} />
    </>
  );
}
