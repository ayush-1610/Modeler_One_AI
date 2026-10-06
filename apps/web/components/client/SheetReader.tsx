"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";

import { apiGet, apiSend } from "@/lib/writes";

import type { ClientFile, ReadPreview, SheetForm, SheetView } from "./types";

/** Study facts a sheet rarely states; they go on the study record, not the recipe. */
type Study = { n: string; design: string; crossover: boolean; population_type: string; infusion_time_min: string; purpose: string };

const PURPOSES: [string, string, string][] = [
  ["model_building", "Model building", "trains the model (e.g. an IV or oral solution study)"],
  ["external_validation", "External validation", "only judges the model (BE studies, fed studies, other formulations)"],
  ["application_verification", "Application verification", "checks the application's prediction (e.g. the BE outcome)"],
];
const CONC_UNITS = ["ng/mL", "µg/mL", "pg/mL", "ng/L", "µg/L", "mg/L", "nmol/L", "µmol/L"];
const ROUTES: [string, string][] = [["oral", "oral"], ["iv_infusion", "IV infusion"], ["iv_bolus", "IV bolus"], ["other", "other"]];
const FORMULATIONS: [string, string][] = [["mr", "modified / extended release (ER, XR, SR)"], ["ir_tablet", "immediate-release tablet"],
  ["ir_capsule", "immediate-release capsule"], ["solution", "solution"], ["suspension", "suspension"], ["other", "other"]];
const ROLES = ["TEST", "RLD", "REFERENCE", "OTHER"];

/** Plain words for the reader's problem codes (modeler_intake.validate, modeler_agents.data_mapping). */
const PROBLEM: Record<string, string> = {
  UNPARSEABLE_VALUE: "Not a number. If it means “no sample”, add it under “cells that mean no sample”",
  UNPARSEABLE_TIME: "The time cannot be read",
  LLOQ_MISSING: "Values below the LLOQ, but no LLOQ: enter it (bioanalytical report)",
  N_MISSING: "Mean values need the number of subjects: fill in “Subjects (n)”",
  MISSING_CONSTANT: "A required detail is empty",
  UNKNOWN_UNIT: "Unit not recognised",
  DUPLICATE_TIME: "Same time twice for one subject: choose the period column, or read each period separately",
  TIME_NOT_INCREASING: "Times go backwards within one series",
  NEGATIVE_VALUE: "Negative value",
  NEGATIVE_TIME: "Negative time",
  DISSOLUTION_OUT_OF_RANGE: "Outside 0–110 % dissolved",
  MISSING_DISSOLUTION_VALUE: "Below-LLOQ text in a dissolution cell",
  PH_OUT_OF_RANGE: "pH outside 0–14",
  UNKNOWN_ROLE: "Role must be TEST, RLD, REFERENCE, SOLUTION or OTHER",
  INVALID_EVIDENCE: "The quoted text is not in that cell",
  INVALID_RECIPE: "The settings are not complete",
  UNKNOWN_SHEET: "Sheet not found",
};

function letter(i: number) {
  let s = "";
  for (let n = i + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
}
const index = (col: string) => col.split("").reduce((a, ch) => a * 26 + ch.charCodeAt(0) - 64, 0) - 1;
const list = (text: string) => text.split(",").map((t) => t.trim()).filter(Boolean);

function Field({ label, hint, children, wide }: { label: string; hint?: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`rf${wide ? " wide" : ""}`}>
      <span className="rf-label">{label}</span>
      {children}
      {hint && <span className="rf-hint">{hint}</span>}
    </label>
  );
}

function ColumnSelect({ value, onChange, columns, header, none, label }: {
  value: string | null; onChange: (v: string | null) => void; columns: string[]; header: (c: string) => string; none?: string;
  label: string;
}) {
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)} aria-label={label}>
      {none && <option value="">{none}</option>}
      {columns.map((c) => <option key={c} value={c}>{c}{header(c) ? ` · ${header(c).slice(0, 28)}` : ""}</option>)}
    </select>
  );
}

/** The sheet as it is, coloured by what the form says each part is. */
function SheetGrid({ view, form }: { view: SheetView; form: SheetForm }) {
  const width = Math.max(1, ...view.rows.map((r) => r.length));
  const values = new Set(form.value_columns);
  const last = form.last_data_row ?? view.rows.length;
  const role = (r: number, c: string) => {
    if (form.layout === "times_down" && c === form.time_column && r >= form.first_data_row) return "g-time";
    if (form.layout === "times_across" && r === form.header_row && values.has(c)) return "g-time";
    if ((c === form.subject_column || c === form.group_column) && r >= form.first_data_row && r <= last) return "g-subject";
    if (values.has(c) && r >= form.first_data_row && r <= last) return "g-value";
    if (r === form.header_row) return "g-header";
    if (r < form.first_data_row || r > last) return "g-out";
    return "";
  };
  return (
    <div className="sheet-grid" role="region" aria-label={`sheet ${view.sheet}`} tabIndex={0}>
      <table>
        <thead><tr><th />{Array.from({ length: width }, (_, i) => <th key={i}>{letter(i)}</th>)}</tr></thead>
        <tbody>
          {view.rows.map((row, r) => (
            <tr key={r}>
              <th>{r + 1}</th>
              {Array.from({ length: width }, (_, c) => (
                <td key={c} className={role(r + 1, letter(c))} title={`${letter(c)}${r + 1}`}>{row[c] ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {view.max_row > view.rows.length && <p className="muted rf-hint">Rows {view.rows.length + 1}–{view.max_row} not shown.</p>}
      <div className="grid-legend">
        <span className="g-header">header</span><span className="g-time">times</span>
        <span className="g-subject">subject / vessel</span><span className="g-value">values read</span>
      </div>
    </div>
  );
}

/** Group the reader's problems by kind: one line each, with where it happens. */
function Problems({ issues }: { issues: ReadPreview["issues"] }) {
  const groups = new Map<string, ReadPreview["issues"]>();
  issues.forEach((i) => groups.set(i.code, [...(groups.get(i.code) ?? []), i]));
  return (
    <ul className="problems" aria-label="Problems found">
      {[...groups.entries()].map(([code, rows]) => (
        <li key={code}>
          <strong>{PROBLEM[code] ?? code}</strong>{rows.length > 1 ? ` (${rows.length} cells)` : ""}:{" "}
          <span className="muted">{rows.slice(0, 4).map((r) => r.location).join(", ")}{rows.length > 4 ? " …" : ""}</span>
          {rows.length === 1 && !PROBLEM[code] && <div className="muted">{rows[0].message}</div>}
          {rows.length >= 1 && PROBLEM[code] && <div className="muted rf-hint">{rows[0].message}</div>}
        </li>
      ))}
    </ul>
  );
}

/**
 * Read one sheet: the sheet on the left, a form on the right filled in from what the sheet states (units, dose, LLOQ
 * quoted from their cells). "Check" shows exactly what would be read and every problem; nothing is kept until "Save".
 */
export function SheetReader({ projectId, file, sheet, last, onSaved, onClose, remember }: {
  projectId: string; file: ClientFile; sheet: string; last: { form: SheetForm; study: Study } | null;
  onSaved: (message: string) => Promise<void>; onClose: () => void; remember: (s: { form: SheetForm; study: Study }) => void;
}) {
  const [view, setView] = useState<SheetView | null>(null);
  const [form, setForm] = useState<SheetForm | null>(null);
  const [study, setStudy] = useState<Study>({ n: "", design: "SD", crossover: false, population_type: "healthy",
                                               infusion_time_min: "", purpose: "model_building" });
  const [blq, setBlq] = useState("");
  const [missing, setMissing] = useState("");
  const [result, setResult] = useState<ReadPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showRecipe, setShowRecipe] = useState(false);

  useEffect(() => {
    let alive = true;
    void apiGet<SheetView>(`/api/v1/projects/${projectId}/client-data/${file.id}/sheets/${encodeURIComponent(sheet)}`).then((env) => {
      if (!alive) return;
      if (!env.data) { setError(env.errors?.[0]?.message ?? "The sheet could not be read."); return; }
      setView(env.data);
      setForm(env.data.form);
      setBlq(env.data.form.below_lloq_tokens.join(", "));
      setMissing(env.data.form.missing_tokens.join(", "));
    });
    return () => { alive = false; };
  }, [projectId, file.id, sheet]);

  const columns = useMemo(() => {
    const width = Math.max(1, ...(view?.rows.map((r) => r.length) ?? [1]));
    return Array.from({ length: width }, (_, i) => letter(i));
  }, [view]);

  if (error && !view) return <div className="banner err">{error}</div>;
  if (!view || !form) return <p className="muted">Reading the sheet…</p>;

  const header = (c: string) => (form.header_row ? view.rows[form.header_row - 1]?.[index(c)] ?? "" : "");
  const set = (patch: Partial<SheetForm>) => { setForm({ ...form, ...patch }); setResult(null); };
  const setConst = (key: string, value: string) => set({ constants: { ...form.constants, [key]: value } });
  const setStudyField = (patch: Partial<Study>) => { setStudy({ ...study, ...patch }); setResult(null); };
  const pk = form.kind === "concentration_time";
  const c = form.constants;
  const first = form.value_columns[0] ?? "";
  const lastCol = form.value_columns[form.value_columns.length - 1] ?? "";
  const setRange = (from: string, to: string) => {
    const [a, b] = [index(from), index(to)].sort((x, y) => x - y);
    set({ value_columns: from && to ? Array.from({ length: b - a + 1 }, (_, i) => letter(a + i)) : [] });
  };

  // what the study record needs before anything can be saved (MS-01 §3.1 study record)
  const needs: string[] = [];
  if (pk) {
    if (!c.study_id?.trim()) needs.push("study id");
    if (!(Number(c.dose) > 0)) needs.push("dose");
    if (!(Number(study.n) > 0)) needs.push("number of subjects");
    if (c.route === "oral" && !c.formulation) needs.push("formulation");
    if (c.route === "iv_infusion" && !(Number(study.infusion_time_min) > 0)) needs.push("infusion time");
  } else {
    if (!c.product?.trim()) needs.push("product");
    if (!c.role) needs.push("role");
    if (!c.medium?.trim()) needs.push("medium");
    if (!c.batch?.trim()) needs.push("batch");
  }
  if (!form.value_columns.length) needs.push("value columns");
  if (form.layout === "times_down" && !form.time_column) needs.push("time column");

  function body(confirm: boolean) {
    const constants = { ...form!.constants };
    if (pk && form!.statistic !== "individual" && !form!.n_column && study.n) constants.n = study.n;
    const facts: Record<string, unknown> = {};
    if (pk) {
      facts.n = Number(study.n);
      facts.design = study.design;
      facts.crossover = study.crossover;
      facts.population_type = study.population_type;
      facts.purpose = study.purpose;
      if (c.route === "iv_infusion") facts.infusion_time_min = Number(study.infusion_time_min);
    }
    return { form: { ...form!, constants, below_lloq_tokens: list(blq), missing_tokens: list(missing) }, study: facts, confirm };
  }

  async function check() {
    setBusy(true);
    const env = await apiSend<ReadPreview>(`/api/v1/projects/${projectId}/client-data/${file.id}:map`, "POST", body(false));
    setBusy(false);
    if (!env.data) { setError(env.errors?.[0]?.message ?? "The sheet could not be checked."); setResult(null); return; }
    setError(null);
    setResult(env.data);
  }

  async function save() {
    setBusy(true);
    const env = await apiSend<ReadPreview>(`/api/v1/projects/${projectId}/client-data/${file.id}:map`, "POST", body(true));
    setBusy(false);
    if (!env.data) { setError(env.errors?.[0]?.message ?? "Not saved."); return; }
    remember({ form: { ...form!, below_lloq_tokens: list(blq), missing_tokens: list(missing) }, study });
    // the saved response carries the page's view (whose "dissolution" is the profiles), so the count is the check's
    const made = pk ? `${env.data.datasets?.length ?? 0} dataset(s) for ${env.data.studies.join(", ")}` : `${result?.dissolution ?? 0} dissolution values`;
    await onSaved(`${sheet}: ${made} saved. Accept them on the Literature page when you have checked them.`);
  }

  function useLast() {
    if (!last) return;
    // the same layout, the details that differ between sheets left to the person
    const keep = last.form.kind === "dissolution" ? { ...last.form.constants, batch: "", ph: "", medium: "" }
                                                  : { ...last.form.constants, study_id: form!.constants.study_id ?? "" };
    // this sheet's own quotes stay; the reader drops any that no longer match what the form says
    setForm({ ...last.form, sheet, evidence: form!.evidence, constants: keep });
    setBlq(last.form.below_lloq_tokens.join(", "));
    setMissing(last.form.missing_tokens.join(", "));
    setStudy(last.study);
    setResult(null);
  }

  const sample = result?.sample;
  return (
    <div className="reader" data-testid={`reader-${sheet}`}>
      <div className="spread">
        <h3 style={{ margin: 0, fontSize: 15, color: "var(--ink)" }}>Read “{sheet}” <span className="muted">· {file.file}</span></h3>
        <div className="row">
          {last && <button className="btn" onClick={useLast}>Same settings as the last sheet</button>}
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
      {view.read_before.length > 0 && (
        <div className="banner warn">
          This sheet was read before ({view.read_before.reduce((n, r) => n + r.datasets.length, 0)} dataset(s)). Reading it again
          adds new data; reject the old datasets on the Literature page if you are replacing them.
        </div>
      )}
      {view.notes.length > 0 && (
        <div className="found">
          <strong>Found in the sheet</strong>
          <ul>{view.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </div>
      )}
      <div className="reader-body">
        <SheetGrid view={view} form={form} />
        <div className="reader-form">
          <fieldset>
            <legend>1 · What the sheet holds</legend>
            <div className="seg" role="radiogroup" aria-label="what the sheet holds">
              <button className={pk ? "on" : ""} onClick={() => set({ kind: "concentration_time", value_unit: "ng/mL" })}>Drug concentrations over time</button>
              <button className={!pk ? "on" : ""} onClick={() => set({ kind: "dissolution", value_unit: "%" })}>Dissolution (% dissolved)</button>
            </div>
          </fieldset>

          <fieldset>
            <legend>2 · Where the numbers are</legend>
            <div className="seg" role="radiogroup" aria-label="layout">
              <button className={form.layout === "times_down" ? "on" : ""} onClick={() => set({ layout: "times_down" })}>One row per time point</button>
              <button className={form.layout === "times_across" ? "on" : ""} onClick={() => set({ layout: "times_across", time_column: null })}>
                Times across the top, one row per {pk ? "subject" : "vessel"}</button>
            </div>
            <div className="rf-grid">
              <Field label={form.layout === "times_across" ? "Row with the times" : "Header row"}>
                <input type="number" min={0} value={form.header_row} onChange={(e) => set({ header_row: Number(e.target.value) })} />
              </Field>
              <Field label="Data from row">
                <input type="number" min={1} value={form.first_data_row} onChange={(e) => set({ first_data_row: Number(e.target.value) })} />
              </Field>
              <Field label="to row" hint="empty: until the first empty row">
                <input type="number" min={1} value={form.last_data_row ?? ""} placeholder="auto"
                       onChange={(e) => set({ last_data_row: e.target.value ? Number(e.target.value) : null })} />
              </Field>
              {form.layout === "times_down" && (
                <Field label="Time column">
                  <ColumnSelect label="time column" value={form.time_column} onChange={(v) => set({ time_column: v })} columns={columns} header={header} none="—" />
                </Field>
              )}
              <Field label={pk ? "Subject column" : "Vessel column"} hint={form.layout === "times_down" ? "only if one column holds every subject" : undefined}>
                <ColumnSelect label="subject column" value={form.subject_column} onChange={(v) => set({ subject_column: v })} columns={columns} header={header} none="none" />
              </Field>
              {pk && (
                <Field label="Period column" hint="when a subject has several rows">
                  <ColumnSelect label="period column" value={form.group_column} onChange={(v) => set({ group_column: v })} columns={columns} header={header} none="none" />
                </Field>
              )}
              <Field label={pk ? "Values from column" : "Vessels from column"}>
                <ColumnSelect label="first value column" value={first} onChange={(v) => setRange(v ?? "", lastCol || v || "")} columns={columns} header={header} none="—" />
              </Field>
              <Field label="to column">
                <ColumnSelect label="last value column" value={lastCol} onChange={(v) => setRange(first || v || "", v ?? "")} columns={columns} header={header} none="—" />
              </Field>
            </div>
          </fieldset>

          <fieldset>
            <legend>3 · Units</legend>
            <div className="rf-grid">
              <Field label="Time unit">
                <select value={form.time_unit} onChange={(e) => set({ time_unit: e.target.value })} aria-label="time unit">
                  <option value="h">hours</option><option value="min">minutes</option>
                </select>
              </Field>
              {pk ? (
                <>
                  <Field label="Concentration unit">
                    <select value={form.value_unit} onChange={(e) => set({ value_unit: e.target.value })} aria-label="concentration unit">
                      {[form.value_unit, ...CONC_UNITS.filter((u) => u.toLowerCase() !== form.value_unit.toLowerCase())].map((u) => <option key={u}>{u}</option>)}
                    </select>
                  </Field>
                  <Field label="Values are">
                    <select value={form.statistic} onChange={(e) => set({ statistic: e.target.value as SheetForm["statistic"] })} aria-label="statistic">
                      <option value="individual">individual subjects</option><option value="arithmetic_mean">arithmetic means</option>
                      <option value="geometric_mean">geometric means</option><option value="median">medians</option>
                    </select>
                  </Field>
                  <Field label={`LLOQ (${form.value_unit})`}>
                    <input type="number" step="any" min={0} value={form.lloq ?? ""} aria-label="LLOQ"
                           onChange={(e) => set({ lloq: e.target.value ? Number(e.target.value) : null })} />
                  </Field>
                  {form.layout === "times_down" && form.statistic !== "individual" && <>
                    <Field label="SD column">
                      <ColumnSelect label="SD column" value={form.sd_column} onChange={(v) => set({ sd_column: v })} columns={columns} header={header} none="none" />
                    </Field>
                    <Field label="N column">
                      <ColumnSelect label="N column" value={form.n_column} onChange={(v) => set({ n_column: v })} columns={columns} header={header} none="none" />
                    </Field>
                  </>}
                  <Field label="Cells that mean below LLOQ" hint="comma-separated, e.g. BLQ, <LLOQ">
                    <input value={blq} onChange={(e) => { setBlq(e.target.value); setResult(null); }} aria-label="below LLOQ texts" />
                  </Field>
                </>
              ) : <Field label="Value unit"><input value="% dissolved" disabled /></Field>}
              <Field label="Cells that mean no sample" hint="skipped, e.g. NS, NR, -">
                <input value={missing} onChange={(e) => { setMissing(e.target.value); setResult(null); }} aria-label="no sample texts" />
              </Field>
              <Field label="Decimal comma">
                <input type="checkbox" checked={form.decimal_comma} onChange={(e) => set({ decimal_comma: e.target.checked })} />
              </Field>
            </div>
          </fieldset>

          {pk ? (
            <fieldset>
              <legend>4 · The study</legend>
              <div className="rf-grid">
                <Field label="Study id" hint="each arm its own, e.g. 230-23-TEST"><input value={c.study_id ?? ""} onChange={(e) => setConst("study_id", e.target.value)} aria-label="study id" /></Field>
                <Field label="Analyte"><input value={c.analyte ?? ""} onChange={(e) => setConst("analyte", e.target.value)} /></Field>
                <Field label="Matrix">
                  <select value={c.matrix ?? "plasma"} onChange={(e) => setConst("matrix", e.target.value)}>
                    {["plasma", "serum", "blood", "urine"].map((m) => <option key={m}>{m}</option>)}
                  </select>
                </Field>
                <Field label="Dose (mg)"><input type="number" step="any" min={0} value={c.dose ?? ""} onChange={(e) => setConst("dose", e.target.value)} aria-label="dose" /></Field>
                <Field label="Route">
                  <select value={c.route ?? "oral"} onChange={(e) => setConst("route", e.target.value)} aria-label="route">
                    {ROUTES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </Field>
                <Field label="Formulation">
                  <select value={c.formulation ?? ""} onChange={(e) => setConst("formulation", e.target.value)} aria-label="formulation">
                    <option value="">choose…</option>
                    {FORMULATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </Field>
                <Field label="Food">
                  <select value={c.food_state ?? "fasted"} onChange={(e) => setConst("food_state", e.target.value)} aria-label="food">
                    <option value="fasted">fasted</option><option value="fed">fed</option>
                  </select>
                </Field>
                {c.route === "iv_infusion" && (
                  <Field label="Infusion time (min)"><input type="number" min={0} value={study.infusion_time_min} onChange={(e) => setStudyField({ infusion_time_min: e.target.value })} /></Field>
                )}
                <Field label="Subjects (n)"><input type="number" min={1} value={study.n} onChange={(e) => setStudyField({ n: e.target.value })} aria-label="subjects" /></Field>
                <Field label="Design">
                  <select value={study.design} onChange={(e) => setStudyField({ design: e.target.value })}>
                    <option value="SD">single dose</option><option value="MD">multiple dose</option>
                  </select>
                </Field>
                <Field label="Population">
                  <select value={study.population_type} onChange={(e) => setStudyField({ population_type: e.target.value })}>
                    <option value="healthy">healthy volunteers</option><option value="patient">patients</option>
                  </select>
                </Field>
                <Field label="Crossover"><input type="checkbox" checked={study.crossover} onChange={(e) => setStudyField({ crossover: e.target.checked })} /></Field>
                <Field label="The study is for" wide hint={PURPOSES.find(([v]) => v === study.purpose)?.[2]}>
                  <select value={study.purpose} onChange={(e) => setStudyField({ purpose: e.target.value })} aria-label="study purpose">
                    {PURPOSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </Field>
              </div>
            </fieldset>
          ) : (
            <fieldset>
              <legend>4 · The profile</legend>
              <div className="rf-grid">
                <Field label="Product" wide hint="as the brief names it, so the plan item and f2 use this profile">
                  <input list={`products-${file.id}`} value={c.product ?? ""} onChange={(e) => setConst("product", e.target.value)} aria-label="product" />
                  <datalist id={`products-${file.id}`}>{view.products.map((p) => <option key={p.name} value={p.name}>{p.role}</option>)}</datalist>
                </Field>
                <Field label="Role">
                  <select value={c.role ?? ""} onChange={(e) => setConst("role", e.target.value)} aria-label="role">
                    <option value="">choose…</option>
                    {ROLES.map((r) => <option key={r}>{r}</option>)}
                  </select>
                </Field>
                <Field label="Strength (mg)"><input type="number" step="any" value={c.strength_mg ?? ""} onChange={(e) => setConst("strength_mg", e.target.value)} /></Field>
                <Field label="Batch / lot"><input value={c.batch ?? ""} onChange={(e) => setConst("batch", e.target.value)} aria-label="batch" /></Field>
                <Field label="Medium"><input value={c.medium ?? ""} onChange={(e) => setConst("medium", e.target.value)} aria-label="medium" placeholder="e.g. phosphate buffer" /></Field>
                <Field label="pH"><input type="number" step="any" value={c.ph ?? ""} onChange={(e) => setConst("ph", e.target.value)} aria-label="pH" /></Field>
                <Field label="Apparatus"><input value={c.apparatus ?? ""} onChange={(e) => setConst("apparatus", e.target.value)} placeholder="e.g. USP II paddle" /></Field>
                <Field label="Speed (rpm)"><input type="number" value={c.rpm ?? ""} onChange={(e) => setConst("rpm", e.target.value)} /></Field>
                <Field label="Volume (mL)"><input type="number" value={c.volume_ml ?? ""} onChange={(e) => setConst("volume_ml", e.target.value)} /></Field>
              </div>
            </fieldset>
          )}

          {form.evidence.length > 0 && (
            <p className="muted rf-hint" style={{ margin: 0 }}>
              Quoted from the sheet: {form.evidence.map((e) => `${e.supports} (${e.cell.split("!")[1]})`).join(" · ")}
            </p>
          )}
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => void check()}>Check what will be read</button>
            <button className="btn primary" disabled={busy || !result?.ready || needs.length > 0} onClick={() => void save()}
                    title={needs.length ? `Fill in: ${needs.join(", ")}` : undefined}>Save these data</button>
          </div>
          {needs.length > 0 && <p className="muted rf-hint" style={{ margin: 0 }}>Still to fill in: {needs.join(", ")}.</p>}
          {error && <div className="banner err">{error}</div>}
          {result && (
            <div className={`read-result ${result.ready ? "ok" : "bad"}`} data-testid="read-result">
              <strong>
                {pk ? `${result.concentrations} values · ${sample?.series.length ?? 0} ${sample?.series.length === 1 ? "series" : "series"} · ${sample?.times.length ?? 0} times`
                    : `${result.dissolution} values · ${sample?.series.length ?? 0} vessels · ${sample?.times.length ?? 0} times`}
                {pk && result.studies.length > 0 && ` · study ${result.studies.join(", ")}`}
                {sample && sample.below_lloq > 0 && ` · ${sample.below_lloq} below LLOQ`}
                {result.ready ? " — ready to save" : " — fix the problems below"}
              </strong>
              {sample && sample.times.length > 0 && (
                <div className="muted rf-hint">Times ({sample.time_unit}): {sample.times.slice(0, 16).join(", ")}{sample.times.length > 16 ? " …" : ""}
                  {" · "}{pk ? "subjects" : "vessels"}: {sample.series.slice(0, 8).join(", ")}{sample.series.length > 8 ? " …" : ""}</div>
              )}
              {sample && sample.rows.length > 0 && (
                <table className="sample">
                  <thead><tr><th>{pk ? "Subject" : "Vessel"}</th><th className="num">Time</th><th className="num">Value</th><th>Cell</th></tr></thead>
                  <tbody>{sample.rows.slice(0, 6).map((r) => (
                    <tr key={r.cell}><td>{r.series}</td><td className="num">{r.time}</td>
                      <td className="num">{sample.values_hidden ? "hidden" : r.blq ? "below LLOQ" : r.value}</td><td><code>{r.cell}</code></td></tr>
                  ))}</tbody>
                </table>
              )}
              {sample?.values_hidden && <p className="muted rf-hint">Values hidden: external data stay blinded until the analysis plan is signed (D-15).</p>}
              {result.issues.length > 0 && <Problems issues={result.issues} />}
              {result.questions.length > 0 && <ul className="problems">{result.questions.map((q) => <li key={q}>{q}</li>)}</ul>}
            </div>
          )}
          <button className="linkish" onClick={() => setShowRecipe(!showRecipe)}>{showRecipe ? "Hide" : "Show"} the reading recipe (what will be kept)</button>
          {showRecipe && <pre className="recipe">{JSON.stringify(result?.recipe ?? body(false).form, null, 2)}</pre>}
        </div>
      </div>
    </div>
  );
}

export type { Study };
