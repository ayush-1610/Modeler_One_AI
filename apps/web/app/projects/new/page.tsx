"use client";

import { useEffect, useState } from "react";

import { Card } from "@/components/ui";
import {
  createProject, getTemplate, listTemplates, prepareCampaign, putCpf, signMap, startCampaign, uploadStudies,
  type PrepareResult, type StudyRow, type TemplateContent, type TemplateSummary,
} from "@/lib/writes";

type Step = 0 | 1 | 2 | 3 | 4;
const STEPS = ["Start from", "Project", "CPF", "Studies", "MAP & run"];

type Envelope<T> = { data: T | null; errors: { message: string }[] };

export default function NewProjectWizard() {
  const [step, setStep] = useState<Step>(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [templates, setTemplates] = useState<TemplateSummary[] | null>(null);
  const [template, setTemplate] = useState<TemplateContent | null>(null);

  const [name, setName] = useState("");
  const [compound, setCompound] = useState("");
  const [question, setQuestion] = useState("");
  const [modelRisk, setModelRisk] = useState("medium");
  const [projectId, setProjectId] = useState("");
  const [questionId, setQuestionId] = useState("");
  const [cpfText, setCpfText] = useState("");
  const [studiesText, setStudiesText] = useState("");
  const [prep, setPrep] = useState<PrepareResult | null>(null);

  async function guard<T>(fn: () => Promise<Envelope<T>>): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      const env = await fn();
      if (env.errors?.length) { setError(env.errors[0].message); return null; }
      if (env.data === null || env.data === undefined) { setError("The API returned no data."); return null; }
      return env.data;
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    guard(() => listTemplates()).then((data) => { if (data) setTemplates(data.templates); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function choose(id: string) {
    const data = await guard(() => getTemplate(id));
    if (!data) return;
    setTemplate(data);
    setName(`${data.compound} ${new Date().toISOString().slice(0, 16).replace("T", " ")}`);
    setCompound(data.compound);
    setQuestion(data.question);
    setModelRisk(data.model_risk);
    setCpfText(JSON.stringify(data.cpf, null, 2));
    setStudiesText(JSON.stringify(data.studies, null, 2));
    setStep(1);
  }

  async function step1() {
    const data = await guard(() => createProject({ name, compound, question, model_risk: modelRisk }));
    if (!data) return;
    setProjectId(data.id);
    setQuestionId(data.questions?.[0]?.id ?? "qoi-1");
    setStep(2);
  }

  async function step2() {
    let cpf: unknown;
    try { cpf = JSON.parse(cpfText); } catch { setError("The CPF is not valid JSON."); return; }
    const data = await guard(() => putCpf(projectId, compound, cpf));
    if (data !== null) setStep(3);
  }

  async function step3() {
    let studies: unknown[];
    try { studies = JSON.parse(studiesText); } catch { setError("The studies are not valid JSON."); return; }
    const data = await guard(() => uploadStudies(projectId, studies));
    if (data) setStep(4);
  }

  async function step4prepare() {
    // Every MS-01 stage; a stage the data cannot support is skipped with its documented reason.
    const data = await guard(() => prepareCampaign(projectId, questionId, { compound, model_risk: modelRisk }));
    if (data) setPrep(data);
  }

  async function signAndStart() {
    if (!prep) return;
    setBusy(true);
    setError(null);
    try {
      // Sign the MAP (Part 11). Under single-node dev auth the principal already carries an loa2 step-up.
      const signed = await signMap(projectId, { record_id: prep.map_id, record_sha256: prep.map_sha256 });
      if (!signed.ok) { setError(`The MAP signature was rejected: ${signed.error ?? "step-up required"}`); return; }
      const started = await startCampaign(projectId, {
        compound, map_id: prep.map_id, cpf_uri: prep.cpf_uri, cpf_sha256: prep.cpf_sha256,
        map_uri: prep.map_uri, observed_uri: prep.observed_uri, question, model_risk: modelRisk, stages: prep.stages,
      });
      // Full navigation (not client-side push) so the monitor's Plotly chart mounts on a clean load.
      if (started.campaign_id) window.location.assign(`/campaigns/${started.campaign_id}`);
      else setError(`The campaign did not start: ${started.error ?? "no campaign id returned"}`);
    } finally {
      setBusy(false);
    }
  }

  let parsedStudies: StudyRow[] = [];
  try { parsedStudies = studiesText ? (JSON.parse(studiesText) as StudyRow[]) : []; } catch { parsedStudies = []; }
  let parsedCpf: TemplateContent["cpf"] | null = null;
  try { parsedCpf = cpfText ? JSON.parse(cpfText) : null; } catch { parsedCpf = null; }

  return (
    <main>
      <h1>New project</h1>
      <p className="muted">Start from a compound, load its Compound Parameter Framework and observed studies, then
        generate and sign the MAP and run the modelling campaign: the whole MS-01 loop, end to end.</p>

      <div className="row" style={{ gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {STEPS.map((label, n) => (
          <span key={label} className={`chip ${n === step ? "brand" : n < step ? "low" : "neutral"}`}>
            {n}. {label}
          </span>
        ))}
      </div>

      {error && <div className="banner err" data-testid="wizard-error" style={{ marginBottom: 14 }}>{error}</div>}

      {step === 0 && (
        <Card title="0 · Start from">
          {!templates && !error && <p className="muted">Loading starting points…</p>}
          <div style={{ display: "grid", gap: 12 }}>
            {templates?.map((t) => (
              <div key={t.id} className="card" style={{ margin: 0 }}>
                <div className="spread">
                  <strong>{t.name}</strong>
                  <span className={`chip ${t.real_data ? "low" : "medium"}`}>
                    {t.real_data ? "real clinical data" : "illustrative, not evidence"}
                  </span>
                </div>
                <p className="muted" style={{ margin: "8px 0" }}>{t.description}</p>
                <button className={`btn ${t.real_data ? "primary" : ""}`} disabled={busy}
                  data-testid={`template-${t.id}`} onClick={() => choose(t.id)}>
                  Use this starting point
                </button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {step === 1 && (
        <Card title="1 · Project and question">
          {template && (
            <p className="muted">Starting point: <strong>{template.name}</strong> ({template.source}).</p>
          )}
          <div className="field"><label>Project name</label>
            <input data-testid="project-name" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="field"><label>Compound</label>
            <input value={compound} onChange={(e) => setCompound(e.target.value)} /></div>
          <div className="field"><label>Question of interest</label>
            <textarea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} /></div>
          <div className="field"><label>Model risk (ICH M15: sets the acceptance tier)</label>
            <select value={modelRisk} onChange={(e) => setModelRisk(e.target.value)}>
              <option value="low">low: 2-fold, ≥ 80 % of studies</option>
              <option value="medium">medium: 1.5-fold, ≥ 80 % of studies</option>
              <option value="high">high: 1.25-fold, every study</option>
            </select></div>
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => setStep(0)}>Back</button>
            <button className="btn primary" disabled={busy} data-testid="create-project" onClick={step1}>
              Create project
            </button>
          </div>
        </Card>
      )}

      {step === 2 && (
        <Card title="2 · Compound Parameter Framework" action={<span className="muted">system of record</span>}>
          <p className="muted">Every simulation is regenerated from these parameters. Values, units and provenance
            are shown as they will be stored.</p>
          {parsedCpf && (
            <div style={{ maxHeight: 320, overflow: "auto", marginBottom: 12 }}>
              <table>
                <thead><tr><th>Parameter</th><th>Value</th><th>Unit</th><th>Status</th></tr></thead>
                <tbody>
                  {parsedCpf.parameters.map((p) => (
                    <tr key={p.id}><td><code>{p.id}</code></td><td>{String(p.value)}</td>
                      <td>{p.unit ?? ""}</td><td>{p.status}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <details>
            <summary className="muted">Edit as JSON</summary>
            <div className="field">
              <textarea rows={16} value={cpfText} onChange={(e) => setCpfText(e.target.value)}
                style={{ fontFamily: "var(--mono, monospace)", fontSize: 12 }} />
            </div>
          </details>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" disabled={busy} onClick={() => setStep(1)}>Back</button>
            <button className="btn primary" disabled={busy} data-testid="save-cpf" onClick={step2}>Save CPF</button>
          </div>
        </Card>
      )}

      {step === 3 && (
        <Card title={`3 · Observed studies (${parsedStudies.length})`}>
          <p className="muted">Clinical studies with observed plasma profiles. The backend converts each to minutes
            and µmol/l and runs deterministic NCA (AUC, Cmax, tmax, t½) for the acceptance gate; the raw profile
            drives fitting. Who was studied decides how MS-01 uses it: patients and special populations never
            train the model.</p>
          <div style={{ maxHeight: 360, overflow: "auto", marginBottom: 12 }}>
            <table>
              <thead><tr><th>Study</th><th>Route</th><th>Dose (mg)</th><th>Form</th><th>Food</th><th>Design</th>
                <th>N</th><th>Population</th><th>Points</th></tr></thead>
              <tbody>
                {parsedStudies.map((s) => (
                  <tr key={s.study_id} title={s.reference}>
                    <td><code>{s.study_id}</code></td><td>{s.route}</td><td>{s.dose_mg}</td>
                    <td>{s.formulation_name ?? s.formulation ?? ""}</td><td>{s.food_state ?? ""}</td>
                    <td>{s.design ?? "SD"}</td><td>{s.n ?? ""}</td><td>{s.special_population ?? "healthy"}</td>
                    <td>{s.profile?.times?.length ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {template && template.skipped.length > 0 && (
            <details style={{ marginBottom: 8 }}>
              <summary className="muted">{template.skipped.length} dataset(s) of the source not used, and why</summary>
              <ul style={{ fontSize: 12 }}>{template.skipped.map((s) => <li key={s}>{s}</li>)}</ul>
            </details>
          )}
          <details>
            <summary className="muted">Edit as JSON</summary>
            <div className="field">
              <textarea rows={14} value={studiesText} onChange={(e) => setStudiesText(e.target.value)}
                style={{ fontFamily: "var(--mono, monospace)", fontSize: 12 }} />
            </div>
          </details>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" disabled={busy} onClick={() => setStep(2)}>Back</button>
            <button className="btn primary" disabled={busy} data-testid="upload-studies" onClick={step3}>
              Upload studies
            </button>
          </div>
        </Card>
      )}

      {step === 4 && (
        <Card title="4 · MAP and campaign">
          {!prep ? (
            <>
              <p className="muted">Generate the Model Analysis Plan from the CPF, studies and question. The study
                split (internal / external) and the acceptance tier are computed deterministically (MS-01 §3).</p>
              <div className="row">
                <button className="btn" disabled={busy} onClick={() => setStep(3)}>Back</button>
                <button className="btn primary" disabled={busy} data-testid="generate-map" onClick={step4prepare}>
                  Generate MAP
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="banner ok" data-testid="map-ready" style={{ marginBottom: 12 }}>
                MAP generated: acceptance tier <strong>{prep.tier}</strong>, {prep.studies.length} study(ies),
                stages {prep.stages.join(" → ")}.
              </div>
              <div style={{ maxHeight: 280, overflow: "auto" }}>
                <table>
                  <thead><tr><th>Study</th><th>Assignment</th></tr></thead>
                  <tbody>
                    {prep.studies.map((s) => (
                      <tr key={s.study_id}><td><code>{s.study_id}</code></td><td>{s.assignment}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>
                Signing the MAP records a Part 11 electronic signature (loa2 step-up). The campaign then runs every
                MS-01 stage on the OSP engine, skipping with its reason any stage your data cannot support, and
                pauses for your signature before prediction (S6). This page opens the live monitor.
              </p>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" disabled={busy} onClick={() => setPrep(null)}>Back</button>
                <button className="btn primary" disabled={busy} data-testid="sign-and-start" onClick={signAndStart}>
                  Sign MAP &amp; start campaign
                </button>
              </div>
            </>
          )}
        </Card>
      )}
    </main>
  );
}
