"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Card } from "@/components/ui";
import { get, narrow, send, type Narrow, type Schema } from "@/lib/api";
import type { ArtifactView } from "@/lib/pipeline";

import { InputsTodo, type TodoItem } from "./InputsTodo";

type Record_ = {
  id: string; value: number | string | null; unit: string | null; status: string; block: string;
  provenance: { source_type: string; reference: string | null; method: string | null; evidence: string | null } | null;
  engine_binding: { process: string | null; parameter: string } | null; candidates?: string[]; placement?: string | null;
};
type Study = { study_id: string; route: string; dose_mg: number; formulation: string; formulation_name?: string; food_state: string;
               n: number; origin: string; evaluable: boolean; purpose: string; dataset_id: string };
type Check = { check: string; ok: boolean; detail: string[] };
// GET /projects/{id}/inputs (InputsPage); the stored CPF records, catalog, readiness and choices are typed here
type View = Narrow<Schema<"InputsPage">, {
  cpf: Narrow<Schema<"CpfVersion">, { assembly: { problems: string[]; records: number } }> | null;
  records: Record_[];
  catalog: ArtifactView<{ studies: Study[]; notes: string[] }> | null;
  readiness: ArtifactView<{ ready: boolean; checks: Check[]; split: Record<string, string[]>; engine_dry_run: string }> | null;
  choices: { process: Record<string, string>; formulation: Record<string, string>; excluded_studies: Record<string, string> };
  published: { studies: string[] } | null;
  todo: TodoItem[];
}>;

const TABS = ["Compound", "Formulations", "Individuals", "Simulation settings", "Studies", "Readiness"] as const;
const SOLID = ["ir_tablet", "ir_capsule", "mr", "suspension"];

function ChoiceForm({ label, options, onSave }: { label: string; options: string[]; onSave: (value: string, reason: string) => Promise<string | null> }) {
  const [value, setValue] = useState(options[0] ?? "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="row" style={{ gap: 4 }}>
      <select value={value} onChange={(e) => setValue(e.target.value)} aria-label={label}>
        {options.map((o) => <option key={o}>{o}</option>)}
      </select>
      <input placeholder="why" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: 160 }} />
      <button className="btn" disabled={!reason.trim() || !value} onClick={async () => setError(await onSave(value, reason))}>Choose</button>
      {error && <span className="banner err">{error}</span>}
    </div>
  );
}

/** P4 model inputs (plan §5.2 P4): CPF v1 by PK-Sim building block, the study catalog, readiness. */
export function ModelInputs({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [view, setView] = useState<View | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Compound");
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const v = await get("/api/v1/projects/{project_id}/inputs", { project_id: projectId });
    if (v.data) { setView(narrow<View>(v.data)); setProblem(null); } else setProblem(v.errors?.[0]?.message ?? "not readable");
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);

  if (problem) return <div className="banner err">{problem}</div>;
  if (!view) return <p className="muted">Loading…</p>;

  const act = async (fn: () => Promise<{ errors: { message: string }[] }>, ok?: string) => {
    const env = await fn();
    if (env.errors?.length) { setMessage({ ok: false, text: env.errors[0].message }); return env.errors[0].message; }
    setMessage(ok ? { ok: true, text: ok } : null);
    await load();
    router.refresh(); // the phase rail is server-rendered
    return null;
  };
  // a decision on the evidence or the datasets, then the inputs assembled again so the list shows what is left
  const run = async (fn: () => Promise<{ errors: { message: string }[] }>, ok: string) => {
    const env = await fn();
    if (env.errors?.length) { setMessage({ ok: false, text: env.errors[0].message }); return env.errors[0].message; }
    return act(() => send("post", "/api/v1/projects/{project_id}/inputs:assemble", { project_id: projectId }), ok || undefined);
  };
  const choose = (kind: Schema<"ChoiceRequest">["kind"], key: string) => (value: string, reason: string) =>
    act(() => send("put", "/api/v1/projects/{project_id}/inputs/choices", { project_id: projectId }, { kind, key, value, reason }));
  const readiness = view.readiness?.content;
  const formulations = view.records.filter((r) => /^form\.[^.]+\.type$/.test(r.id)).map((r) => r.id.split(".")[1]);
  const studies = view.catalog?.content?.studies ?? [];

  return (
    <>
      <Card title="CPF v1 and readiness">
        <div className="row">
          <button className="btn primary" data-testid="assemble" onClick={() => act(() => send("post", "/api/v1/projects/{project_id}/inputs:assemble", { project_id: projectId }),
                                                                            "Assembled from the accepted evidence and datasets.")}>
            Assemble from the accepted evidence
          </button>
          <button className="btn" data-testid="accept-inputs" disabled={!readiness?.ready || view.readiness?.status === "APPROVED"}
                  onClick={() => act(() => send("post", "/api/v1/projects/{project_id}/inputs:accept", { project_id: projectId }), "Inputs accepted (P4).")}>
            Accept the inputs
          </button>
          <button className="btn" data-testid="publish-inputs" disabled={view.readiness?.status !== "APPROVED"}
                  onClick={() => act(() => send("post", "/api/v1/projects/{project_id}/inputs:publish", { project_id: projectId }), "Handed to the model plan (P5).")}>
            Hand to the model plan
          </button>
        </div>
        {view.cpf && (
          <p className="muted" style={{ margin: "6px 0 0", fontSize: 13 }}>
            CPF v{view.cpf.version} · {view.cpf.assembly.records} parameters · {view.cpf.status.toLowerCase()}
            {view.readiness && <> · readiness <span className={`chip ${readiness?.ready ? "low" : "high"}`} data-testid="ready-chip">
              {readiness?.ready ? "ready" : "not ready"}</span> {view.readiness.status === "APPROVED" ? "· accepted" : ""}</>}
            {view.published && <> · handed to the plan ({view.published.studies.length} {view.published.studies.length === 1 ? "study" : "studies"})</>}
          </p>
        )}
        {message && <div className={`banner ${message.ok ? "ok" : "err"}`} style={{ marginTop: 8 }} role="status">{message.text}</div>}
      </Card>
      {view.cpf && <InputsTodo projectId={projectId} todo={view.todo ?? []} run={run} />}
      <nav className="tabs" aria-label="PK-Sim building blocks">
        {TABS.map((t) => <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t}</button>)}
      </nav>
      {tab !== "Studies" && tab !== "Readiness" && (
        <Card title={tab}>
          <table>
            <thead><tr><th>Parameter</th><th className="num">Value</th><th>PK-Sim unit</th><th>Status</th><th>Value origin</th><th>PK-Sim place</th></tr></thead>
            <tbody>
              {view.records.filter((r) => r.block === tab).map((r) => (
                <tr key={r.id} data-testid={`record-${r.id}`}>
                  <td><code>{r.id}</code></td>
                  <td className="num">{r.value === null ? "—" : typeof r.value === "number" ? +r.value.toPrecision(5) : r.value}</td>
                  <td>{r.unit ?? "—"}</td>
                  <td><span className={`chip ${r.status === "MISSING" ? "high" : r.status === "PREDICTED" ? "medium" : "low"}`}>{r.status.toLowerCase()}</span></td>
                  <td title={r.provenance?.reference ?? ""} style={{ fontSize: 13 }}>
                    {r.provenance ? <>{r.provenance.source_type}{r.provenance.method ? ` · ${r.provenance.method}` : ""}
                      <div className="muted" style={{ fontSize: 12 }}>{r.provenance.reference}</div></> : "—"}
                  </td>
                  <td style={{ fontSize: 13 }}>
                    {r.engine_binding ? <>{r.engine_binding.process ?? r.engine_binding.parameter}<div className="muted">{r.engine_binding.parameter}</div></>
                      : r.candidates?.length ? <ChoiceForm label={`process for ${r.id}`} options={r.candidates}
                                                           onSave={choose("process", r.id.split(".").slice(0, -1).join("."))} />
                      : r.placement === "reference" ? <span className="muted">kept for checks; PK-Sim computes it</span>
                      : <span className="muted">{r.block}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {view.records.filter((r) => r.block === tab).length === 0 && <p className="muted" style={{ margin: 0 }}>Nothing in this building block yet.</p>}
        </Card>
      )}
      {tab === "Studies" && (
        <Card title={`Studies (${studies.length})`}>
          <table>
            <thead><tr><th>Study</th><th>Protocol</th><th>Origin</th><th>Formulation</th><th>Judged</th></tr></thead>
            <tbody>
              {studies.map((s) => (
                <tr key={s.study_id} data-testid={`study-${s.study_id}`}>
                  <td><strong>{s.study_id}</strong><div className="muted" style={{ fontSize: 12 }}>{s.purpose.replace(/_/g, " ")} · n {s.n}</div></td>
                  <td>{s.route.replace("_", " ")} · {s.dose_mg} mg · {s.food_state}</td>
                  <td><span className={`chip ${["SYNTHETIC", "ILLUSTRATIVE"].includes(s.origin) ? "high" : "low"}`}>{s.origin.toLowerCase().replace("_", " ")}</span></td>
                  <td>{SOLID.includes(s.formulation)
                    ? (s.formulation_name ?? (formulations.length ? <ChoiceForm label={`formulation of ${s.study_id}`} options={formulations}
                                                                          onSave={choose("formulation", s.study_id)} />
                                                             : <span className="muted">no formulation in the CPF yet</span>))
                    : s.formulation}</td>
                  <td>{s.evaluable ? "profile" : <span className="muted">not judged</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(view.catalog?.content?.notes ?? []).length > 0 && <ul className="flags">{view.catalog?.content?.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
        </Card>
      )}
      {tab === "Readiness" && (
        <Card title="Readiness (S0 and the software build)">
          {!readiness ? <p className="muted" style={{ margin: 0 }}>Assemble first.</p> : (
            <>
              <table>
                <tbody>
                  {readiness.checks.map((c) => (
                    <tr key={c.check} data-testid={`check-${c.check}`}>
                      <td><span className={`chip ${c.ok ? "low" : "high"}`}>{c.ok ? "ok" : "open"}</span></td>
                      <td>{c.check}{c.detail.length > 0 && <ul className="flags">{c.detail.map((d) => <li key={d}>{d}</li>)}</ul>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {Object.keys(readiness.split).length > 0 && (
                <p className="muted" style={{ fontSize: 13 }}>Default MS-01 split: {Object.entries(readiness.split)
                  .map(([k, v]) => `${k.toLowerCase()} ${v.join(", ")}`).join(" · ")}</p>
              )}
              <p className="muted" style={{ fontSize: 13 }}>PK-Sim dry run: {readiness.engine_dry_run}</p>
            </>
          )}
        </Card>
      )}
    </>
  );
}
