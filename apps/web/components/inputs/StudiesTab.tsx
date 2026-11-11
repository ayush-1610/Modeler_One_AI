"use client";

import { useState } from "react";

import type { Act, Retag } from "@/components/client/ClientFiles";
import type { View as ClientView } from "@/components/client/types";
import { EmptyState, InlineIssue, LabeledControl, ReasonField, WaitingFor } from "@/components/kit";
import { SortHeader, TableFilter, TableMore } from "@/components/kit/SortableTable";
import { apiFile, send, type Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { numericKey, ordinal, useTableView } from "@/lib/tableView";

import { type Run, TodoCard, type TodoItem } from "./InputsTodo";
import { ObservedDatasets } from "./ObservedDatasets";
import { FilesHere } from "./TabFiles";

export type StudyRow = Schema<"InputStudyRow">;
export type Options = Record<"route" | "formulation" | "food_state" | "purpose" | "sex" | "population", string[]>;

const ROLE: Record<string, string> = {
  S1: "calibration (IV)", S2: "calibration (oral)", S3: "calibration (formulation)", S5: "external validation",
  S6: "application", SUPPORTIVE: "supportive",
};

const fact = (s: StudyRow, key: string) => s.facts[key] as string | number | null | undefined;

// the Role column sorts in the pipeline's order, not alphabetically
const roleOrder = ordinal(["S1", "S2", "S3", "S5", "S6", "SUPPORTIVE"]);
const SHOW = [
  { id: "all", label: "All", test: () => true },
  { id: "used", label: "Used", test: (s: StudyRow) => !s.excluded },
  { id: "out", label: "Left out", test: (s: StudyRow) => Boolean(s.excluded) },
  { id: "blinded", label: "Blinded", test: (s: StudyRow) => s.blinded },
  { id: "unjudged", label: "No mean profile", test: (s: StudyRow) => !s.evaluable && !s.excluded },
] as const;
type Show = (typeof SHOW)[number]["id"];
const STUDY_KEYS = {
  study: (s: StudyRow) => s.study_id,
  protocol: (s: StudyRow) => `${String(fact(s, "route") ?? "")} ${String(numericKey(fact(s, "dose_mg")) ?? "").padStart(12, "0")}`,
  role: (s: StudyRow) => roleOrder(s.role),
  used: (s: StudyRow) => (s.excluded ? 1 : 0),
};
const studyText = (s: StudyRow) => [s.study_id, s.purpose, s.origin, fact(s, "formulation"), fact(s, "formulation_name"), fact(s, "route")]
  .filter(Boolean).join(" ").replace(/_/g, " ");

/** The studies table: sortable by its heads, filtered by text or by where a study stands, 20 rows at a time. A study
 *  that needs the person (blinded, its regimen missing) or whose row is being typed in is never paged or hidden by the text filter (a pressed chip narrows it too). */
function StudiesTable({ studies, projectId, run, onIndividuals }: {
  studies: StudyRow[]; projectId: string; run: Run; onIndividuals: () => void;
}) {
  const [show, setShow] = useState<Show>("all");
  // a row the person has typed in (a regimen, a reason) stays shown, so its text is not lost; it is not counted as
  // needing attention, and focus alone (tabbing through) does not pin it
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set());
  const view = useTableView({
    rows: studies, keys: STUDY_KEYS, text: studyText, pageSize: 20,
    filter: SHOW.find((x) => x.id === show)!.test, filterKey: show,
    keep: (s) => s.blinded || s.regimen_missing, pin: (s) => touched.has(s.study_id),
  });
  const touch = (id: string) => { if (!touched.has(id)) setTouched(new Set([...touched, id])); };
  return (
    <div>
      <TableFilter view={view} placeholder="Filter studies: id, purpose, origin, formulation…" label="Filter the studies"
                   testId="studies-filter">
        <div className="table-chips" role="group" aria-label="Show studies">
          {SHOW.map((x) => (
            <button key={x.id} type="button" aria-pressed={show === x.id} data-testid={`studies-show-${x.id}`}
                    onClick={() => setShow(x.id)}>{x.label}</button>
          ))}
        </div>
      </TableFilter>
      <div className="table-scroll">
        <table className="studies-table">
          <caption className="sr-only">Studies</caption>
          <thead><tr>
            <SortHeader view={view} col="study" label="Study" /><SortHeader view={view} col="protocol" label="Protocol" />
            <SortHeader view={view} col="role" label="Role" /><th>Individual</th><th>Regimen</th>
            <SortHeader view={view} col="used" label="Used" />
          </tr></thead>
          <tbody className="paged-rows">
            {view.visible.map((s) => (
              <tr key={s.study_id} data-testid={`study-${s.study_id}`} id={`study-${s.study_id}`} className={s.excluded ? "left-out" : ""}
                  onInput={() => touch(s.study_id)}>
                <td><strong>{s.study_id}</strong>
                  <div className="muted fs-12">{(s.purpose ?? "").replace(/_/g, " ")} · {(s.origin ?? "").toLowerCase().replace("_", " ")}</div>
                  {s.blinded && <span className="chip medium" title="its values are hidden until the MAP is signed">blinded</span>}</td>
                <td>{String(fact(s, "route") ?? "").replace("_", " ")} · {fact(s, "dose_mg")} {s.facts.dose_per_kg ? "mg/kg" : "mg"} ·{" "}
                  {fact(s, "food_state")} · {fact(s, "formulation_name") ?? fact(s, "formulation")} · n {fact(s, "n")}
                  {!s.evaluable && !s.excluded && <div className="muted fs-12">no mean profile: not judged</div>}</td>
                <td>{s.role ? <span className="chip neutral" title={s.role_source === "proposed"
                  ? "proposed by the MS-01 split; changed on Review & sign, with a reason" : "the plan's placement"}>
                  {s.role} · {ROLE[s.role] ?? s.role.toLowerCase()}</span> : <span className="muted">—</span>}</td>
                <td><button type="button" className="link-btn" onClick={onIndividuals}>
                  {{ entered: "entered", published: "published individual", default: "healthy adult default", missing: "not stated" }[s.demographics]}
                </button></td>
                <td><Regimen s={s} projectId={projectId} run={run} /></td>
                <td>{s.excluded && <div className="muted fs-12">left out: {s.excluded}</div>}
                  <LeaveOut s={s} projectId={projectId} run={run} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {view.visible.length === 0 && <p className="muted table-none">No study matches this filter.</p>}
      <TableMore view={view} noun="studies" testId="studies-more" />
    </div>
  );
}

function Regimen({ s, projectId, run }: { s: StudyRow; projectId: string; run: Run }) {
  const [doses, setDoses] = useState("");
  const [every, setEvery] = useState("");
  if (fact(s, "design") !== "MD") return <span className="muted">single dose</span>;
  if (!s.regimen_missing) return <span>{fact(s, "n_doses")} doses every {fact(s, "dosing_interval_h")} h</span>;
  return (
    <div className="row gap-4">
      <input placeholder="doses" value={doses} onChange={(x) => setDoses(x.target.value)} className="w-70" aria-label={`doses for ${s.study_id}`} />
      <input placeholder="every (h)" value={every} onChange={(x) => setEvery(x.target.value)} className="w-80" aria-label={`interval for ${s.study_id}`} />
      <button className="btn primary" disabled={!s.dataset_id || !(Number(doses) > 0 && Number(every) > 0)}
              onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/datasets/{dataset_id}:study",
                                                 { project_id: projectId, dataset_id: s.dataset_id ?? "" },
                                                 { changes: { n_doses: Number(doses), dosing_interval_h: Number(every) } }),
                                      `${s.study_id}: ${doses} doses every ${every} h.`)}>Save</button>
    </div>
  );
}

/** Leave a study out of the model, or take it back, with the reason (kept with the inputs and shown at the review). One
 *  small button per row; the reason is asked for only when it is pressed (the 2026-11-11 audit, item 4). */
function LeaveOut({ s, projectId, run }: { s: StudyRow; projectId: string; run: Run }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const verb = s.excluded ? "Include again" : "Leave out";
  if (!open) {
    return (
      <button type="button" className="link-btn" onClick={() => setOpen(true)}
              aria-label={s.excluded ? `Include ${s.study_id} again` : `Leave ${s.study_id} out`}>{verb}…</button>
    );
  }
  return (
    <div className="ctl-row" onKeyDown={(x) => { if (x.key === "Escape") setOpen(false); }}>
      <ReasonField autoFocus placeholder={s.excluded ? "why include it again" : "why leave it out"} value={reason}
                   onChange={setReason} className="w-160" ariaLabel={`reason for ${s.study_id}`} />
      <button className="btn" disabled={!reason.trim()}
              onClick={() => void run(() => send("put", "/api/v1/projects/{project_id}/inputs/choices", { project_id: projectId },
                                                 { kind: "excluded_studies", key: s.study_id, value: s.excluded ? null : reason, reason }),
                                      s.excluded ? `${s.study_id} is used again.` : `${s.study_id} is left out: ${reason}.`)}>
        {verb}
      </button>
      <button type="button" className="link-btn" onClick={() => setOpen(false)}>Cancel</button>
    </div>
  );
}

const list = (text: string) => text.split(/[\s,;]+/).filter(Boolean).map(Number);

/** A table typed in by hand (the fallback when no sheet or figure can be read): the study's facts, its mean profile and
 *  the source (POST /datasets; the manual path). */
function TypedTable({ projectId, run, options }: { projectId: string; run: Run; options: Options }) {
  const [f, setF] = useState({ study_id: "", route: "oral", dose_mg: "", formulation: "solution", food_state: "fasted", n: "",
                               purpose: "model_building", time_unit: "h", unit: "ng/ml", times: "", values: "", title: "", link: "",
                               origin: "LITERATURE", analyte: "", product: "" });
  // a model system: each study names the analyte it measures and the product it gives (MS-01 v1.3 §6.5); chosen, never guessed
  const system = useResource("/api/v1/projects/{project_id}/system", { project_id: projectId }).data?.system ?? null;
  const set = (k: keyof typeof f) => (x: { target: { value: string } }) => setF({ ...f, [k]: x.target.value });
  const times = list(f.times), values = list(f.values);
  const example = f.origin === "ILLUSTRATIVE";
  // each condition of "Add the study", said in words beside the button (2026-11-11 audit 2, item 7): never a silent disable
  const doseBad = f.dose_mg.trim() !== "" && !(Number(f.dose_mg) > 0);
  const nBad = f.n.trim() !== "" && !(Number.isInteger(Number(f.n)) && Number(f.n) > 0);
  const needed = [
    !f.study_id.trim() && "the study id",
    !(Number(f.dose_mg) > 0) && "the dose, a number above 0 in mg",
    !(Number.isInteger(Number(f.n)) && Number(f.n) > 0) && "n, the number of subjects",
    times.some(Number.isNaN) && "times as numbers only",
    values.some(Number.isNaN) && "concentrations as numbers only",
    times.length < 2 && "at least two times",
    times.length > 1 && times.length !== values.length && "one concentration per time",
    !(example || f.title.trim() || f.link.trim()) && "a source title or link",
    system && !f.analyte && "the analyte measured",
    system && !f.product && "the product given",
  ].filter((x): x is string => Boolean(x));
  const ok = needed.length === 0;
  const pick = (k: keyof typeof f, values: string[]) => (
    <select value={f[k]} onChange={set(k)} aria-label={k.replace("_", " ")}>{values.map((v) => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>)}</select>
  );
  return (
    <div className="typed-table" data-testid="typed-table">
      <div className="ctl-row">
        <LabeledControl label="Study id" required className="w-140">
          <input placeholder="study id" value={f.study_id} onChange={set("study_id")} aria-label="study id" />
        </LabeledControl>
        <LabeledControl label="Route">{pick("route", options.route)}</LabeledControl>
        <LabeledControl label="Dose (mg)" required className="w-110">
          <input placeholder="dose (mg)" value={f.dose_mg} onChange={set("dose_mg")} aria-label="dose" inputMode="decimal"
                 aria-invalid={doseBad} />
        </LabeledControl>
        <LabeledControl label="Formulation">{pick("formulation", options.formulation)}</LabeledControl>
        <LabeledControl label="Food">{pick("food_state", options.food_state)}</LabeledControl>
        <LabeledControl label="Subjects (n)" required className="w-110">
          <input placeholder="n" value={f.n} onChange={set("n")} aria-label="subjects" inputMode="numeric" aria-invalid={nBad} />
        </LabeledControl>
        <LabeledControl label="Purpose">{pick("purpose", options.purpose)}</LabeledControl>
        <LabeledControl label="Where the data come from">
          <select value={f.origin} onChange={set("origin")} aria-label="where the data come from" data-testid="typed-origin">
            <option value="LITERATURE">a published table or text</option>
            <option value="CLIENT">the client&apos;s data</option>
            <option value="ILLUSTRATIVE">example data (test only, never evidence)</option>
          </select>
        </LabeledControl>
      </div>
      {doseBad && <InlineIssue severity="warn" testId="typed-dose-issue">The dose must be a number above 0, in mg (no unit in the field).</InlineIssue>}
      {nBad && <InlineIssue severity="warn" testId="typed-n-issue">n must be a whole number of subjects above 0.</InlineIssue>}
      {system && (
        <div className="row gap-6 mt-4">
          <select value={f.analyte} onChange={set("analyte")} aria-label="analyte measured" data-testid="typed-analyte">
            <option value="">analyte measured…</option>
            {system.analytes.map((a) => (
              <option key={a.name} value={a.name}>
                {a.name}{a.judged_at.length ? ` (judged at ${a.judged_at.join(", ")})` : " (reported, not judged)"}
              </option>
            ))}
          </select>
          <select value={f.product} onChange={set("product")} aria-label="product given" data-testid="typed-product">
            <option value="">product given…</option>
            {Object.keys(system.products).map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
      )}
      <div className="ctl-row mt-4">
        <LabeledControl label="Times" required className="flex-1 minw-180">
          <input placeholder="e.g. 0.5 1 2 4 8" value={f.times} onChange={set("times")} aria-label="times"
                 aria-invalid={times.some(Number.isNaN)} />
        </LabeledControl>
        <LabeledControl label="Time unit" className="w-90">
          <input placeholder="unit" value={f.time_unit} onChange={set("time_unit")} aria-label="time unit" />
        </LabeledControl>
        <LabeledControl label="Mean concentrations" required className="flex-1 minw-180">
          <input placeholder="one per time" value={f.values} onChange={set("values")} aria-label="values"
                 aria-invalid={values.some(Number.isNaN)} />
        </LabeledControl>
        <LabeledControl label="Concentration unit" className="w-110">
          <input placeholder="unit" value={f.unit} onChange={set("unit")} aria-label="concentration unit" />
        </LabeledControl>
      </div>
      <div className="ctl-row mt-4">
        <LabeledControl label={example ? "Source title" : "Source title (or a link)"} className="flex-1 minw-180">
          <input placeholder="source title" value={f.title} onChange={set("title")} aria-label="source title" />
        </LabeledControl>
        <LabeledControl label="DOI or URL" className="w-200">
          <input placeholder="DOI or URL" value={f.link} onChange={set("link")} aria-label="source link" />
        </LabeledControl>
        <button className="btn primary" disabled={!ok}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/datasets", { project_id: projectId }, {
                  study: { study_id: f.study_id.trim(), route: f.route, dose_mg: Number(f.dose_mg), formulation: f.formulation,
                           food_state: f.food_state, n: Number(f.n), n_timepoints: times.length,
                           ...(system ? { analyte: f.analyte, product: f.product } : {}) },
                  ...(system ? { analyte: f.analyte } : {}),
                  time_unit: f.time_unit, unit: f.unit, purpose: f.purpose,
                  origin: f.origin as "LITERATURE" | "CLIENT" | "ILLUSTRATIVE",
                  series: [{ times, values, n: Number(f.n), statistic: "arithmetic_mean" }],
                  source: { title: f.title, ...(f.link.startsWith("10.") ? { doi: f.link } : f.link ? { url: f.link } : {}) },
                }), `${f.study_id}: the typed table is added.`)}>
          Add the study
        </button>
      </div>
      {!ok && <p className="waiting-for m-4-0" data-testid="typed-needed">Still needed: {needed.join(", ")}.</p>}
      {times.length !== values.length && values.length > 0 && <p className="inline-issue warn">{times.length} times but {values.length} values.</p>}
    </div>
  );
}

/** The Studies tab (redesign §3.2): each study with its facts, the role the MS-01 split proposes (changed only on Review
 *  & sign), whether it is blinded (D-15), its regimen and whether it is used; then the client's clinical and
 *  bioanalytical files (plan 2026-11-05 §3.1), each data sheet read by the reading agent for the person to check and save
 *  (R3c), and the other ways to add observed data. */
export function StudiesTab({ studies, todo, projectId, run, options, onIndividuals, client, onRetag, onSaved }: {
  studies: StudyRow[]; todo: TodoItem[]; projectId: string; run: Run; options: Options; onIndividuals: () => void;
  client: ClientView | undefined; onRetag: Retag; onSaved: (message: string) => void;
}) {
  const act: Act = (fn) => run(fn, "");
  const unpromised = client?.reconciliation.unpromised ?? [];
  const [typing, setTyping] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  async function template() {
    const { file, problem } = await apiFile("/api/v1/client-data/template.xlsx");
    setProblem(file ? null : `The template could not be downloaded: ${problem}`);
    if (!file) return;
    const url = URL.createObjectURL(file);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${client?.template ?? "ModelerOne_ClientData"}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <>
      {todo.map((t, i) => <TodoCard key={`${t.kind}-${t.target}-${i}`} t={t} projectId={projectId} run={run} />)}
      {studies.length === 0 ? <EmptyState title="No studies yet">Add observed data below: the client&apos;s sheets, a published
        figure or a table typed in.</EmptyState> : (
        <StudiesTable studies={studies} projectId={projectId} run={run} onIndividuals={onIndividuals} />
      )}
      <FilesHere tab="studies" projectId={projectId} client={client} act={act} onRetag={onRetag} onSaved={async (m) => onSaved(m)}>
        <p className="muted fs-13 m-0-0-8">
          The reading agent proposes how to read each data sheet, and code checks every proposal: each quote is in its cell and the
          reading applies without a problem. Open a sheet, check what it reads against the sheet, correct anything wrong and save.
          {client && !client.agents.enabled && " Agents are off: the form is filled in first by code."}
        </p>
      </FilesHere>
      {unpromised.length > 0 && (
        <section className="client-files">
          <h4 className="m-12-0-4">Delivered, not in the data checklist</h4>
          <ul className="flags" data-testid="unpromised">{unpromised.map((u) => <li key={u}>{u}</li>)}</ul>
        </section>
      )}
      <section className="add-data" data-testid="add-data">
        <h3>Add observed data</h3>
        <ul>
          <li>The client&apos;s files, with “Add files” at the top of this area (workbooks are sorted sheet by sheet; PDF and
            Word reports are read for their data; a file named as dissolution or formulation goes to Products and dissolution),
            or fill the{" "}
            <button type="button" className="link-btn" onClick={template} data-testid="download-template">client-data template</button>,
            which is read cell by cell with no AI.</li>
          <li>Digitize a published figure against calibrated axes, or let the observed-data agent search, under
            {" "}<a href="#observed-datasets">Every dataset</a>.</li>
          <li><button type="button" className="link-btn" onClick={() => setTyping(!typing)} data-testid="type-table">
            {typing ? "Close the typed table" : "Type a table in by hand"}</button></li>
        </ul>
        {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
        {typing && <TypedTable projectId={projectId} run={run} options={options} />}
      </section>
      <div id="observed-datasets"><ObservedDatasets projectId={projectId} run={run} /></div>
    </>
  );
}
