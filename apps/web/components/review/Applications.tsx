"use client";

// The applications (redesign §3.3 "VBE, its own panel" and "Other applications"; R4c). The VBE crossover is set here:
// its inputs are the template's (vbe-crossover, DRAFT until the SME approves it), the never-defaulted ones stay empty
// until a person gives them, and the validator lists what is still missing. Every other application of the brief says
// what the campaign does with it; the ones S6 cannot run yet are said here, and acknowledged become limitations.

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import type { Envelope, Schema } from "@/lib/api";
import { planApi, type PlanView } from "@/lib/plan";
import type { ReviewPage } from "@/lib/review";

type Apply = <T>(call: () => Promise<Envelope<T>>, ok?: string) => Promise<string | null>;
type Pinned = Schema<"PinnedApplication">;
type Variability = { parameter: string; cv_percent: string; source: string };
type BeMetric = { gmr: string; cv: string };

const STATUS: Record<string, { label: string; chip: string }> = {
  runs: { label: "runs at S6", chip: "brand" },
  campaign: { label: "the campaign", chip: "neutral" },
  partial: { label: "partly supported", chip: "medium" },
  not_supported: { label: "not supported yet", chip: "high" },
};
const BE_METRICS = ["AUC_inf", "C_max"] as const;

const text = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const num = (v: string) => (v.trim() === "" ? undefined : Number(v));

function asPayload(apps: Pinned[], template: string, inputs: Record<string, unknown> | null) {
  const others = apps.filter((a) => a.template !== template)
    .map((a) => ({ template: a.template, inputs: Object.fromEntries(a.inputs.filter((i) => i.value !== null).map((i) => [i.id, i.value])) }));
  return inputs === null ? others : [...others, { template, inputs }];
}

function VbePanel({ projectId, app, all, apply }: { projectId: string; app: Pinned; all: Pinned[]; apply: Apply }) {
  const value = (id: string) => app.inputs.find((i) => i.id === id)?.value as unknown;
  const be = value("observed_be") as { metrics?: Record<string, { gmr?: number; between_subject_cv_percent?: number }>; source?: string } | null;
  const [test, setTest] = useState(text(value("test_formulation")));
  const [ref, setRef] = useState(text(value("reference_formulation")));
  const [rows, setRows] = useState<Variability[]>(((value("variability") as Variability[] | null) ?? [])
    .map((r) => ({ parameter: text(r.parameter), cv_percent: text(r.cv_percent), source: text(r.source) })));
  const [design, setDesign] = useState({ n_subjects: text(value("n_subjects")), n_trials: text(value("n_trials")),
                                         seed: text(value("seed")), pos_threshold: text(value("pos_threshold")) });
  const [limits, setLimits] = useState(text(value("limits")) || "standard");
  const [observed, setObserved] = useState<Record<string, BeMetric>>(Object.fromEntries(BE_METRICS.map((m) => [m, {
    gmr: text(be?.metrics?.[m]?.gmr), cv: text(be?.metrics?.[m]?.between_subject_cv_percent) }])));
  const [beSource, setBeSource] = useState(text(be?.source));
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const observedGiven = BE_METRICS.some((m) => observed[m].gmr || observed[m].cv) || beSource.trim() !== "";
  const inputs = (): Record<string, unknown> => {
    const out: Record<string, unknown> = { limits };
    if (test) out.test_formulation = test;
    if (ref) out.reference_formulation = ref;
    const variability = rows.filter((r) => r.parameter.trim() || r.cv_percent || r.source.trim())
      .map((r) => ({ parameter: r.parameter.trim(), cv_percent: num(r.cv_percent), source: r.source.trim() }));
    if (variability.length) out.variability = variability;
    for (const [key, raw] of Object.entries(design)) if (num(raw) !== undefined) out[key] = num(raw);
    if (observedGiven) {
      out.observed_be = {
        metrics: Object.fromEntries(BE_METRICS.filter((m) => observed[m].gmr || observed[m].cv)
          .map((m) => [m, { gmr: num(observed[m].gmr), between_subject_cv_percent: num(observed[m].cv) }])),
        source: beSource.trim(),
      };
    }
    return out;
  };
  const save = async () => {
    const failed = await apply(() => planApi.structure(projectId, "applications", asPayload(all, app.template, inputs()), reason.trim()),
                               "The VBE design is saved.");
    setProblem(failed);
    if (!failed) setReason("");
  };
  const label = (id: string) => app.inputs.find((i) => i.id === id)?.label ?? id;
  const design_ = (id: keyof typeof design, hint: string) => (
    <label className="vbe-field">{label(id)}
      <input value={design[id]} inputMode="decimal" data-testid={`vbe-${id}`} placeholder={hint}
             onChange={(e) => setDesign({ ...design, [id]: e.target.value })} />
    </label>
  );

  return (
    <div className="vbe-panel" data-testid="vbe-panel">
      <p className="muted review-note">Template <code>{app.template}</code> {app.version} · {app.status}, provisional until the SME
        approves it. Inputs marked never defaulted stay empty until you give them.</p>
      {app.formulations.length < 2 && (
        <InlineIssue severity="warn">The CPF has {app.formulations.length === 0 ? "no formulation" : "one formulation"}: the TEST and
          reference products come from the Formulations tab of Inputs (form.&#123;name&#125;.*).</InlineIssue>
      )}
      <div className="vbe-grid">
        <label className="vbe-field">{label("test_formulation")}
          <select value={test} onChange={(e) => setTest(e.target.value)} data-testid="vbe-test_formulation">
            <option value="">—</option>{app.formulations.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        <label className="vbe-field">{label("reference_formulation")}
          <select value={ref} onChange={(e) => setRef(e.target.value)} data-testid="vbe-reference_formulation">
            <option value="">—</option>{app.formulations.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        {design_("n_subjects", "e.g. 24")}
        {design_("n_trials", "e.g. 100")}
        {design_("seed", "a whole number ≥ 1")}
        {design_("pos_threshold", "e.g. 0.8")}
        <label className="vbe-field">{label("limits")}
          <select value={limits} onChange={(e) => setLimits(e.target.value)} data-testid="vbe-limits">
            {app.limits.map((l) => (
              <option key={l.id} value={l.id}>{`${l.id}: ${(l.lower * 100).toFixed(2)}–${(l.upper * 100).toFixed(2)} % at ${l.ci_level * 100} % CI`}
                {l.verified ? "" : " [VERIFY], unverified"}</option>
            ))}
          </select>
        </label>
      </div>

      <h3>{label("variability")}</h3>
      <p className="muted review-note">The PK-Sim parameter path, its CV and the source of that CV, never defaulted. The engine checks each path
        before the trials run: an unknown path stops the VBE, it never runs without it.</p>
      <table className="review-table vbe-variability">
        <thead><tr><th>PK-Sim parameter path</th><th>CV %</th><th>Source</th><th /></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} data-testid={`vbe-variability-${i}`}>
              <td><input value={r.parameter} aria-label={`parameter ${i + 1}`} placeholder="Organism|…"
                         onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, parameter: e.target.value } : x)))} /></td>
              <td><input value={r.cv_percent} inputMode="decimal" aria-label={`CV ${i + 1}`}
                         onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, cv_percent: e.target.value } : x)))} /></td>
              <td><input value={r.source} aria-label={`source ${i + 1}`} placeholder="the study the CV comes from"
                         onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, source: e.target.value } : x)))} /></td>
              <td><button type="button" className="link-btn" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" className="btn tiny" data-testid="vbe-variability-add"
              onClick={() => setRows([...rows, { parameter: "", cv_percent: "", source: "" }])}>Add a parameter</button>

      <h3>{label("observed_be")} <span className="muted">(optional)</span></h3>
      {!observedGiven && (
        <InlineIssue severity="note"><span data-testid="vbe-not-validated-warning">Without an observed BE study the result will be NOT
          VALIDATED (F-304): it cannot support a bioequivalence decision on its own.</span></InlineIssue>
      )}
      <div className="vbe-grid">
        {BE_METRICS.map((m) => (
          <div key={m} className="vbe-field">
            <span>{m}</span>
            <input value={observed[m].gmr} inputMode="decimal" placeholder="observed GMR" data-testid={`vbe-be-${m}-gmr`}
                   onChange={(e) => setObserved({ ...observed, [m]: { ...observed[m], gmr: e.target.value } })} />
            <input value={observed[m].cv} inputMode="decimal" placeholder="between-subject CV %" data-testid={`vbe-be-${m}-cv`}
                   onChange={(e) => setObserved({ ...observed, [m]: { ...observed[m], cv: e.target.value } })} />
          </div>
        ))}
        <label className="vbe-field">Source of the observed study
          <input value={beSource} onChange={(e) => setBeSource(e.target.value)} data-testid="vbe-be-source" />
        </label>
      </div>

      {app.problems.length > 0 && (
        <ul className="limitations vbe-problems" data-testid="vbe-problems">{app.problems.map((p) => <li key={p}>{p}</li>)}</ul>
      )}
      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="why this design (required)"
               aria-label="why this VBE design" style={{ flex: 1, minWidth: 220 }} data-testid="vbe-reason" />
        <button type="button" className="btn tiny primary" disabled={!reason.trim()} onClick={save} data-testid="vbe-save">Save</button>
      </div>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </div>
  );
}

function AddApplication({ projectId, template, all, apply }: { projectId: string; template: string; all: Pinned[]; apply: Apply }) {
  const [reason, setReason] = useState("");
  return (
    <div className="row" style={{ gap: 8 }}>
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="why add it (required)" aria-label={`why add ${template}`} />
      <button type="button" className="btn tiny" disabled={!reason.trim()} data-testid={`add-${template}`}
              onClick={() => apply(() => planApi.structure(projectId, "applications", [...asPayload(all, template, null), { template, inputs: {} }],
                                                          reason.trim()))}>
        Add the {template === "vbe-crossover" ? "VBE" : template} application</button>
    </div>
  );
}

function Acknowledge({ projectId, violation, apply }: { projectId: string; violation: PlanView["violations"][number]; apply: Apply }) {
  const [reason, setReason] = useState("");
  if (violation.acknowledged) return <div className="muted review-note">acknowledged: {violation.acknowledged}</div>;
  return (
    <span className="review-exclude">
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="acknowledge, with why" aria-label={`acknowledge ${violation.target}`} />
      <button type="button" className="btn tiny" disabled={!reason.trim()} data-testid={`acknowledge-${violation.target}`}
              onClick={() => apply(() => planApi.acknowledge(projectId, violation.id, reason.trim()))}>Acknowledge</button>
    </span>
  );
}

export function Applications({ projectId, view, review, apply }: { projectId: string; view: PlanView; review: ReviewPage; apply: Apply }) {
  const { pinned, addable } = review.applications;
  const support = review.application_support;
  const warning = (code: string) => view.violations.find((v) => v.rule === "application-unsupported" && v.target === code);
  return (
    <div className="applications" data-testid="review-applications">
      <h3>Virtual bioequivalence</h3>
      {pinned.filter((a) => a.template === "vbe-crossover").map((a) => <VbePanel key={a.template} projectId={projectId} app={a} all={pinned} apply={apply} />)}
      {addable.map((t) => <AddApplication key={t} projectId={projectId} template={t} all={pinned} apply={apply} />)}
      {!pinned.length && !addable.length && <p className="muted">The brief names no application S6 runs (APP-14 virtual bioequivalence).</p>}

      <h3>The brief&apos;s applications</h3>
      {support.rows.length === 0 ? <p className="muted">The brief names no application.</p> : (
        <table className="review-table">
          <thead><tr><th>Application</th><th>What the campaign does</th></tr></thead>
          <tbody>
            {support.rows.map((r) => {
              const w = warning(r.code);
              return (
                <tr key={r.code} data-testid={`application-${r.code}`}>
                  <td>{r.label}</td>
                  <td><span className={`chip ${STATUS[r.status]?.chip ?? "neutral"}`}>{STATUS[r.status]?.label ?? r.status}</span>{" "}
                    <span className="review-note">{r.reason}</span>
                    {w && <Acknowledge projectId={projectId} violation={w} apply={apply} />}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {support.scenarios.length > 0 && <>
        <h3>The brief&apos;s prediction scenarios</h3>
        <p className="muted review-note">Recorded with the project. S6 simulates the validated studies, not these regimens yet.</p>
        <ul className="validation-studies">
          {support.scenarios.map((s, i) => (
            <li key={i} data-testid={`scenario-${i}`}>
              {Object.entries(s).map(([k, v]) => `${k.replaceAll("_", " ")}: ${String(v)}`).join(" · ")}
              <span className="chip neutral">not simulated yet</span>
            </li>
          ))}
        </ul>
      </>}
    </div>
  );
}
