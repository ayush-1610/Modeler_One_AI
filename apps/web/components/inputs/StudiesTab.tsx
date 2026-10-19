"use client";

import Link from "next/link";
import { useState } from "react";

import { type Act, ClientFiles } from "@/components/client/ClientData";
import type { View as ClientView } from "@/components/client/types";
import { EmptyState, InlineIssue } from "@/components/kit";
import { apiFile, send, type Schema } from "@/lib/api";

import { type Run, TodoCard, type TodoItem } from "./InputsTodo";

export type StudyRow = Schema<"InputStudyRow">;
export type Options = Record<"route" | "formulation" | "food_state" | "purpose" | "sex" | "population", string[]>;

const ROLE: Record<string, string> = {
  S1: "calibration (IV)", S2: "calibration (oral)", S3: "calibration (formulation)", S5: "external validation",
  S6: "application", SUPPORTIVE: "supportive",
};

const fact = (s: StudyRow, key: string) => s.facts[key] as string | number | null | undefined;

function Regimen({ s, projectId, run }: { s: StudyRow; projectId: string; run: Run }) {
  const [doses, setDoses] = useState("");
  const [every, setEvery] = useState("");
  if (fact(s, "design") !== "MD") return <span className="muted">single dose</span>;
  if (!s.regimen_missing) return <span>{fact(s, "n_doses")} doses every {fact(s, "dosing_interval_h")} h</span>;
  return (
    <div className="row" style={{ gap: 4 }}>
      <input placeholder="doses" value={doses} onChange={(x) => setDoses(x.target.value)} style={{ width: 70 }} aria-label={`doses for ${s.study_id}`} />
      <input placeholder="every (h)" value={every} onChange={(x) => setEvery(x.target.value)} style={{ width: 80 }} aria-label={`interval for ${s.study_id}`} />
      <button className="btn primary" disabled={!s.dataset_id || !(Number(doses) > 0 && Number(every) > 0)}
              onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:study",
                                                 { project_id: projectId, dataset_id: s.dataset_id ?? "" },
                                                 { changes: { n_doses: Number(doses), dosing_interval_h: Number(every) } }),
                                      `${s.study_id}: ${doses} doses every ${every} h.`)}>Save</button>
    </div>
  );
}

/** Leave a study out of the model, or take it back, with the reason (kept with the inputs and shown at the review). */
function LeaveOut({ s, projectId, run }: { s: StudyRow; projectId: string; run: Run }) {
  const [reason, setReason] = useState("");
  return (
    <div className="row" style={{ gap: 4 }}>
      <input placeholder={s.excluded ? "why include it again" : "why leave it out"} value={reason} onChange={(x) => setReason(x.target.value)}
             style={{ width: 160 }} aria-label={`reason for ${s.study_id}`} />
      <button className="btn" disabled={!reason.trim()}
              onClick={() => void run(() => send("put", "/api/v1/projects/{project_id}/inputs/choices", { project_id: projectId },
                                                 { kind: "excluded_studies", key: s.study_id, value: s.excluded ? null : reason, reason }),
                                      s.excluded ? `${s.study_id} is used again.` : `${s.study_id} is left out: ${reason}.`)}>
        {s.excluded ? "Include again" : "Leave out"}
      </button>
    </div>
  );
}

const list = (text: string) => text.split(/[\s,;]+/).filter(Boolean).map(Number);

/** A table typed in by hand (the fallback when no sheet or figure can be read): the study's facts, its mean profile and
 *  the source (POST /datasets; the manual path). */
function TypedTable({ projectId, run, options }: { projectId: string; run: Run; options: Options }) {
  const [f, setF] = useState({ study_id: "", route: "oral", dose_mg: "", formulation: "solution", food_state: "fasted", n: "",
                               purpose: "model_building", time_unit: "h", unit: "ng/ml", times: "", values: "", title: "", link: "" });
  const set = (k: keyof typeof f) => (x: { target: { value: string } }) => setF({ ...f, [k]: x.target.value });
  const times = list(f.times), values = list(f.values);
  const ok = f.study_id.trim() && Number(f.dose_mg) > 0 && Number(f.n) > 0 && times.length > 1 && times.length === values.length
    && !times.some(Number.isNaN) && !values.some(Number.isNaN) && (f.title.trim() || f.link.trim());
  const pick = (k: keyof typeof f, values: string[]) => (
    <select value={f[k]} onChange={set(k)} aria-label={k.replace("_", " ")}>{values.map((v) => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>)}</select>
  );
  return (
    <div className="typed-table" data-testid="typed-table">
      <div className="row" style={{ gap: 6 }}>
        <input placeholder="study id" value={f.study_id} onChange={set("study_id")} style={{ width: 140 }} aria-label="study id" />
        {pick("route", options.route)}
        <input placeholder="dose (mg)" value={f.dose_mg} onChange={set("dose_mg")} style={{ width: 90 }} aria-label="dose" />
        {pick("formulation", options.formulation)}
        {pick("food_state", options.food_state)}
        <input placeholder="n" value={f.n} onChange={set("n")} style={{ width: 60 }} aria-label="subjects" />
        {pick("purpose", options.purpose)}
      </div>
      <div className="row" style={{ gap: 6, marginTop: 4 }}>
        <input placeholder="times, e.g. 0.5 1 2 4 8" value={f.times} onChange={set("times")} style={{ flex: 1, minWidth: 180 }} aria-label="times" />
        <input placeholder="unit" value={f.time_unit} onChange={set("time_unit")} style={{ width: 60 }} aria-label="time unit" />
        <input placeholder="mean concentrations" value={f.values} onChange={set("values")} style={{ flex: 1, minWidth: 180 }} aria-label="values" />
        <input placeholder="unit" value={f.unit} onChange={set("unit")} style={{ width: 80 }} aria-label="concentration unit" />
      </div>
      <div className="row" style={{ gap: 6, marginTop: 4 }}>
        <input placeholder="source title" value={f.title} onChange={set("title")} style={{ flex: 1, minWidth: 180 }} aria-label="source title" />
        <input placeholder="DOI or URL" value={f.link} onChange={set("link")} style={{ width: 200 }} aria-label="source link" />
        <button className="btn primary" disabled={!ok}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/datasets", { project_id: projectId }, {
                  study: { study_id: f.study_id.trim(), route: f.route, dose_mg: Number(f.dose_mg), formulation: f.formulation,
                           food_state: f.food_state, n: Number(f.n), n_timepoints: times.length },
                  time_unit: f.time_unit, unit: f.unit, purpose: f.purpose,
                  series: [{ times, values, n: Number(f.n), statistic: "arithmetic_mean" }],
                  source: { title: f.title, ...(f.link.startsWith("10.") ? { doi: f.link } : f.link ? { url: f.link } : {}) },
                }), `${f.study_id}: the typed table is added.`)}>
          Add the study
        </button>
      </div>
      {times.length !== values.length && values.length > 0 && <p className="inline-issue warn">{times.length} times but {values.length} values.</p>}
    </div>
  );
}

/** The Studies tab (redesign §3.2): each study with its facts, the role the MS-01 split proposes (changed only on Review
 *  & sign), whether it is blinded (D-15), its regimen and whether it is used; then the client's files, each data sheet
 *  read by the reading agent for the person to check and save (R3c), and the other ways to add observed data. */
export function StudiesTab({ studies, todo, projectId, run, options, onIndividuals, client, onSaved }: {
  studies: StudyRow[]; todo: TodoItem[]; projectId: string; run: Run; options: Options; onIndividuals: () => void;
  client: ClientView | undefined; onSaved: (message: string) => void;
}) {
  const act: Act = (fn) => run(fn, "");
  const workbooks = client?.files.filter((f) => f.triage.length > 0 && !f.template) ?? [];
  const [typing, setTyping] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  async function template() {
    const { file, problem } = await apiFile("/api/v1/client-data/template.xlsx");
    setProblem(file ? null : `The template could not be downloaded: ${problem}`);
    if (!file) return;
    const url = URL.createObjectURL(file);
    const a = document.createElement("a");
    a.href = url;
    a.download = "ModelerOne_ClientData.xlsx";
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <>
      {todo.map((t, i) => <TodoCard key={`${t.kind}-${t.target}-${i}`} t={t} projectId={projectId} run={run} />)}
      {studies.length === 0 ? <EmptyState title="No studies yet">Add observed data below: the client&apos;s sheets, a published
        figure or a table typed in.</EmptyState> : (
        <div className="table-scroll">
          <table className="studies-table">
            <thead><tr><th>Study</th><th>Protocol</th><th>Role</th><th>Individual</th><th>Regimen</th><th>Used</th></tr></thead>
            <tbody>
              {studies.map((s) => (
                <tr key={s.study_id} data-testid={`study-${s.study_id}`} id={`study-${s.study_id}`} className={s.excluded ? "left-out" : ""}>
                  <td><strong>{s.study_id}</strong>
                    <div className="muted" style={{ fontSize: 12 }}>{(s.purpose ?? "").replace(/_/g, " ")} · {(s.origin ?? "").toLowerCase().replace("_", " ")}</div>
                    {s.blinded && <span className="chip medium" title="its values are hidden until the MAP is signed (D-15)">blinded</span>}</td>
                  <td>{String(fact(s, "route") ?? "").replace("_", " ")} · {fact(s, "dose_mg")} {s.facts.dose_per_kg ? "mg/kg" : "mg"} ·{" "}
                    {fact(s, "food_state")} · {fact(s, "formulation_name") ?? fact(s, "formulation")} · n {fact(s, "n")}
                    {!s.evaluable && !s.excluded && <div className="muted" style={{ fontSize: 12 }}>no mean profile: not judged</div>}</td>
                  <td>{s.role ? <span className="chip neutral" title={s.role_source === "proposed"
                    ? "proposed by the MS-01 split; changed on Review & sign, with a reason" : "the plan's placement"}>
                    {s.role} · {ROLE[s.role] ?? s.role.toLowerCase()}</span> : <span className="muted">—</span>}</td>
                  <td><button type="button" className="link-btn" onClick={onIndividuals}>
                    {{ entered: "entered", published: "published individual", default: "healthy adult default", missing: "not stated" }[s.demographics]}
                  </button></td>
                  <td><Regimen s={s} projectId={projectId} run={run} /></td>
                  <td>{s.excluded && <div className="muted" style={{ fontSize: 12 }}>left out: {s.excluded}</div>}
                    <LeaveOut s={s} projectId={projectId} run={run} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {client && workbooks.length > 0 && (
        <section className="client-files" data-testid="studies-client-files">
          <h3>The client&apos;s sheets</h3>
          <p className="muted" style={{ fontSize: 13, margin: "0 0 8px" }}>
            The reading agent proposes how to read each data sheet, and code checks every proposal: each quote is in its cell and the
            reading applies without a problem. Open a sheet, check what it reads against the sheet, correct anything wrong and save.
            {!client.agents.enabled && " Agents are off: the form is filled in first by code."}
          </p>
          <ClientFiles projectId={projectId} view={{ ...client, files: workbooks }} act={act} onSaved={async (m) => onSaved(m)} />
        </section>
      )}
      <section className="add-data" data-testid="add-data">
        <h3>Add observed data</h3>
        <ul>
          <li>Add the client&apos;s files on <Link href={`/projects/${projectId}/client-data`}>Client data</Link>, or fill the{" "}
            <button type="button" className="link-btn" onClick={template}>client-data template</button>, which is read cell by cell
            with no AI.</li>
          <li><Link href={`/projects/${projectId}/evidence`}>Digitize a published figure</Link> against calibrated axes.</li>
          <li><button type="button" className="link-btn" onClick={() => setTyping(!typing)} data-testid="type-table">
            {typing ? "Close the typed table" : "Type a table in by hand"}</button></li>
        </ul>
        {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
        {typing && <TypedTable projectId={projectId} run={run} options={options} />}
      </section>
    </>
  );
}
