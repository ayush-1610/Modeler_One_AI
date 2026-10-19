"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Dissolution } from "@/components/client/ClientData";
import type { View as ClientView } from "@/components/client/types";
import { InlineIssue, PageShell, SidePanel } from "@/components/kit";
import { narrow, send, type Envelope, type Narrow, type Schema } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";
import { type ArtifactView, STEP_ROUTES } from "@/lib/pipeline";

import { StudyIndividuals } from "./IndividualsTab";
import { InputRows, type Row } from "./InputRows";
import { LABEL, ORDER, type Run, TITLE, type TodoItem } from "./InputsTodo";
import { type Options, StudiesTab } from "./StudiesTab";

type Tab = "compound" | "formulations" | "individuals" | "settings" | "studies";
const TABS: [Tab, string][] = [["compound", "Compound"], ["formulations", "Formulations"], ["individuals", "Individuals"],
                               ["settings", "Simulation settings"], ["studies", "Studies"]];
const TAB_LABEL = Object.fromEntries(TABS) as Record<Tab, string>;
const SOLID = ["ir_tablet", "ir_capsule", "mr", "suspension"];

type Check = { check: string; ok: boolean; detail: string[] };
// GET /projects/{id}/inputs (InputsPage): the readiness, choices and the open items are typed here
type View = Narrow<Schema<"InputsPage">, {
  readiness: ArtifactView<{ ready: boolean; checks: Check[]; split: Record<string, string[]>; engine_dry_run: string }> | null;
  todo: TodoItem[];
}>;

function FormulationChoice({ study, options, projectId, run }: { study: string; options: string[]; projectId: string; run: Run }) {
  const [value, setValue] = useState(options[0] ?? "");
  const [reason, setReason] = useState("");
  return (
    <div className="row" style={{ gap: 4 }}>
      <select value={value} onChange={(e) => setValue(e.target.value)} aria-label={`formulation of ${study}`}>
        {options.map((o) => <option key={o}>{o}</option>)}
      </select>
      <input placeholder="why" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: 160 }} />
      <button className="btn" disabled={!reason.trim() || !value}
              onClick={() => void run(() => send("put", "/api/v1/projects/{project_id}/inputs/choices", { project_id: projectId },
                                                 { kind: "formulation", key: study, value, reason }), `${study}: ${value}.`)}>Choose</button>
    </div>
  );
}

/** Step 2 · Inputs (redesign §3.2): one workspace in PK-Sim's building blocks. Values flow in from every source not
 *  excluded and the source-selection rule keeps one per input (D-32); the side list says what is still missing to run,
 *  and each item opens where it is settled. Nothing is accepted here: the one review is at the MAP signature (D-27). */
export function InputsWorkspace({ projectId }: { projectId: string }) {
  const page = useResource("/api/v1/projects/{project_id}/inputs", { project_id: projectId }, { select: (d) => narrow<View>(d) });
  const client = useResource("/api/v1/projects/{project_id}/client-data", { project_id: projectId },
    { select: (d) => narrow<ClientView>(d), poll: (d) => d.running });
  const mutation = useMutation();
  const [tab, setTab] = useState<Tab>("compound");
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const assembled = useRef(false);
  const view = page.data;

  const run: Run = async <T,>(fn: () => Promise<Envelope<T>>, ok: string) => {
    const { problem } = await mutation.run(fn);
    setNotice(problem ? { ok: false, text: problem } : ok ? { ok: true, text: ok } : null);
    return problem;
  };

  // the inputs follow every change on the server; a page opened after a change upstream (the brief) assembles them once
  const stale = view && (!view.readiness || view.readiness.status === "STALE");
  useEffect(() => {
    if (!stale || assembled.current) return;
    assembled.current = true;
    void run(() => send("post", "/api/v1/projects/{project_id}/inputs:assemble", { project_id: projectId }), "");
  }, [stale]); // eslint-disable-line react-hooks/exhaustive-deps

  if (page.problem) return <div className="banner err">{page.problem}</div>;
  if (!view) return <p className="muted">Loading the inputs…</p>;

  const todo = [...view.todo].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
  const forTab = (t: Tab) => todo.filter((i) => (i.tab ?? "compound") === t);
  const rows = (t: Tab) => (view.compound as Row[]).filter((r) => r.tab === t);
  const readiness = view.readiness?.content;
  const options = view.study_options as Options;
  const studies = view.studies;
  const used = studies.filter((s) => !s.excluded);
  const formulations = view.compound.filter((r) => /^form\.[^.]+\.type$/.test(r.id) && r.state === "kept").map((r) => r.id.split(".")[1]);

  function open(t: TodoItem) {
    setTab((t.tab ?? "compound") as Tab);
    window.setTimeout(() => document.getElementById(`todo-${t.kind}-${t.target}`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 50);
  }

  return (
    <PageShell
      eyebrow="Step 2 of 4"
      title="Inputs"
      lede={<>Every value not excluded flows in; where sources give several, one is kept by source and grade and the others
        stay listed for the review. Values are never averaged. <span className="muted">({view.selection_rule})</span></>}
      actions={(
        <button type="button" className="btn" data-testid="ask-literature"
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence:research", { project_id: projectId }),
                                        "The literature agent is searching; its values flow into the rows.")}>
          Ask the literature for what is missing
        </button>
      )}
      side={(
        <>
          {todo.length > 0 ? (
            <SidePanel title={`Still missing to run (${todo.length})`} tone="warn" testId="still-missing">
              <ul className="missing-list">
                {todo.map((t, i) => (
                  <li key={`${t.kind}-${t.target}-${i}`}>
                    <button type="button" className="link-btn" onClick={() => open(t)} data-testid={`missing-${t.kind}-${t.target}`}>
                      {TITLE[t.kind]}{t.kind !== "datasets" && t.kind !== "check" ? ` · ${LABEL[t.target] ?? t.target}` : ""}
                    </button>
                    <span className="muted"> · {TAB_LABEL[(t.tab ?? "compound") as Tab]}</span>
                  </li>
                ))}
              </ul>
            </SidePanel>
          ) : readiness?.ready ? (
            <SidePanel title="Inputs are ready" tone="ok" testId="inputs-ready">
              <p style={{ margin: "0 0 8px" }}>Everything S0 needs is here, and every planned simulation builds.</p>
              <Link className="btn primary" href={STEP_ROUTES.review(projectId)}>Go to Review &amp; sign</Link>
            </SidePanel>
          ) : (
            <SidePanel title="Assembling" testId="assembling"><p style={{ margin: 0 }}>The inputs are being put together.</p></SidePanel>
          )}
          {readiness && (
            <SidePanel title="Readiness">
              <ul className="checks" data-testid="readiness">
                {readiness.checks.map((c) => (
                  <li key={c.check} data-testid={`check-${c.check}`}>
                    <span className={`chip ${c.ok ? "low" : "high"}`}>{c.ok ? "ok" : "open"}</span> {c.check}
                  </li>
                ))}
              </ul>
              <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>PK-Sim dry run: {readiness.engine_dry_run}</p>
            </SidePanel>
          )}
          <SidePanel title="Where values come from">
            <p style={{ margin: 0, fontSize: 13 }}>The client&apos;s files, the literature agent, PubChem and the published OSP model.
              The <Link href={`/projects/${projectId}/evidence`}>Literature</Link> and <Link href={`/projects/${projectId}/client-data`}>Client
              data</Link> pages stay open until they are retired.</p>
          </SidePanel>
        </>
      )}
    >
      {notice && <div className={`banner ${notice.ok ? "ok" : "err"}`} role="status" data-testid="inputs-notice">{notice.text}</div>}
      <nav className="tabs" aria-label="PK-Sim building blocks" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "active" : ""}
                  onClick={() => setTab(id)} data-testid={`tab-${id}`}>
            {label}{forTab(id).length > 0 && <span className="tab-count">{forTab(id).length}</span>}
          </button>
        ))}
      </nav>

      {tab === "compound" && (
        <InputRows rows={rows("compound")} todo={forTab("compound")} projectId={projectId} run={run}
                   empty="The compound's values appear here as the client's files, the literature and PubChem fill them." />
      )}

      {tab === "formulations" && (
        <>
          <InputRows rows={rows("formulations")} todo={forTab("formulations")} projectId={projectId} run={run}
                     empty="No formulation yet: a solution needs none; a tablet's release comes from its dissolution profile or the literature." />
          {used.some((s) => SOLID.includes(String(s.facts.formulation))) && (
            <section className="card">
              <h3 style={{ marginTop: 0 }}>The formulation of each solid study</h3>
              <table>
                <tbody>
                  {used.filter((s) => SOLID.includes(String(s.facts.formulation))).map((s) => (
                    <tr key={s.study_id} data-testid={`formulation-${s.study_id}`}>
                      <td><strong>{s.study_id}</strong> <span className="muted">{String(s.facts.formulation).replace("_", " ")}</span></td>
                      <td>{s.facts.formulation_name ? String(s.facts.formulation_name)
                        : formulations.length ? <FormulationChoice study={s.study_id} options={formulations} projectId={projectId} run={run} />
                          : <span className="muted">no formulation in the model yet</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
          {client.data && client.data.dissolution.profiles.length > 0 && (
            <Dissolution projectId={projectId} d={client.data.dissolution}
                         act={async (fn) => run(fn, "The release model is proposed; its values flow into the formulation.")} />
          )}
        </>
      )}

      {tab === "individuals" && (
        <>
          {forTab("individuals").filter((t) => t.kind !== "demographics").length > 0 && (
            <InputRows rows={[]} todo={forTab("individuals").filter((t) => t.kind !== "demographics")} projectId={projectId} run={run} empty="" />
          )}
          <h3>Each study&apos;s individual</h3>
          <StudyIndividuals studies={studies} projectId={projectId} run={run} options={options} />
          <h3>Values set on the individual</h3>
          <InputRows rows={rows("individuals")} todo={[]} projectId={projectId} run={run}
                     empty="None: enzyme and transporter expression and individual values appear here when a source gives them." />
        </>
      )}

      {tab === "settings" && (
        <>
          <InputRows rows={rows("settings")} todo={forTab("settings")} projectId={projectId} run={run}
                     empty="The calculation methods are PK-Sim's defaults unless the published model sets them." />
          <section className="card">
            <h3 style={{ marginTop: 0 }}>Solver settings</h3>
            <table>
              <tbody>
                {used.map((s) => {
                  const solver = (s.facts.solver ?? {}) as Record<string, number>;
                  return (
                    <tr key={s.study_id}>
                      <td><strong>{s.study_id}</strong></td>
                      <td>{Object.keys(solver).length ? Object.entries(solver).map(([k, v]) => `${k} ${v}`).join(" · ")
                        : <span className="muted">PK-Sim&apos;s defaults</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <InlineIssue severity="note">Each study is simulated over its whole sampled window. Prediction regimens are applications,
              set on Review &amp; sign.</InlineIssue>
          </section>
        </>
      )}

      {tab === "studies" && (
        <StudiesTab studies={studies} todo={forTab("studies")} projectId={projectId} run={run} options={options}
                    onIndividuals={() => setTab("individuals")} client={client.data ?? undefined}
                    onSaved={(m) => setNotice({ ok: true, text: m })} />
      )}
    </PageShell>
  );
}
