"use client";

import { useState } from "react";

import { Card } from "@/components/ui";
import { ACICLOVIR_CPF, ACICLOVIR_STUDIES } from "@/lib/templates";
import { createProject, prepareCampaign, putCpf, signMap, startCampaign, uploadStudies, type PrepareResult } from "@/lib/writes";

type Step = 1 | 2 | 3 | 4;

export default function NewProjectWizard() {
  const [step, setStep] = useState<Step>(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("Aciclovir FIH");
  const [compound, setCompound] = useState("Aciclovir");
  const [question, setQuestion] = useState("First-in-human renal starting dose from IV disposition");
  const [projectId, setProjectId] = useState("");
  const [questionId, setQuestionId] = useState("");
  const [cpfText, setCpfText] = useState(JSON.stringify(ACICLOVIR_CPF, null, 2));
  const [studiesText, setStudiesText] = useState(JSON.stringify(ACICLOVIR_STUDIES, null, 2));
  const [prep, setPrep] = useState<PrepareResult | null>(null);

  async function guard<T>(fn: () => Promise<{ data: T | null; errors: { message: string }[] }>): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      const env = await fn();
      if (env.errors?.length) { setError(env.errors[0].message); return null; }
      return env.data;
    } catch {
      setError("Could not reach the API — is the backend running (MODELER_EXECUTION_BACKEND=local)?");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function step1() {
    const data = await guard(() => createProject({ name, compound, question, model_risk: "medium" }));
    if (!data) return;
    setProjectId(data.id);
    setQuestionId(data.questions?.[0]?.id ?? "qoi-1");
    setStep(2);
  }

  async function step2() {
    let cpf: unknown;
    try { cpf = JSON.parse(cpfText); } catch { setError("CPF is not valid JSON"); return; }
    const data = await guard(() => putCpf(projectId, compound, cpf));
    if (data !== null) setStep(3);
  }

  async function step3() {
    let studies: unknown[];
    try { studies = JSON.parse(studiesText); } catch { setError("Studies are not valid JSON"); return; }
    const data = await guard(() => uploadStudies(projectId, studies));
    if (data) setStep(4);
  }

  async function step4prepare() {
    // IV-only Aciclovir dataset → S0 readiness + S1 IV disposition (add oral studies to enable S2+).
    const data = await guard(() => prepareCampaign(projectId, questionId, { compound, stages: ["S0", "S1"] }));
    if (data) setPrep(data);
  }

  async function signAndStart() {
    if (!prep) return;
    setBusy(true);
    setError(null);
    try {
      // Sign the MAP (Part 11). Under single-node dev auth the principal already carries an loa2 step-up.
      const signed = await signMap(projectId, { record_id: prep.map_id, record_sha256: prep.map_sha256 });
      if (!signed) { setError("MAP signature was rejected (step-up required)."); return; }
      const started = await startCampaign(projectId, {
        compound, map_id: prep.map_id, cpf_uri: prep.cpf_uri, cpf_sha256: prep.cpf_sha256,
        map_uri: prep.map_uri, observed_uri: prep.observed_uri, question, model_risk: "medium", stages: prep.stages,
      });
      // Full navigation (not client-side push) so the monitor's Plotly chart mounts on a clean load.
      if (started.campaign_id) window.location.assign(`/campaigns/${started.campaign_id}`);
      else setError("The campaign did not start.");
    } catch {
      setError("Could not reach the API to sign and start the campaign.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>New project</h1>
      <p className="muted">Create a project, seed its Compound Parameter Framework and observed studies, then
        generate and sign the MAP and start a modeling campaign — the whole MS-01 loop, end to end.</p>

      <div className="row" style={{ gap: 8, marginBottom: 16 }}>
        {[1, 2, 3, 4].map((n) => (
          <span key={n} className={`chip ${n === step ? "brand" : n < step ? "low" : "neutral"}`}>
            {n}. {["Project", "CPF", "Studies", "MAP & run"][n - 1]}
          </span>
        ))}
      </div>

      {error && <div className="banner err" style={{ marginBottom: 14 }}>{error}</div>}

      {step === 1 && (
        <Card title="1 · Project and question">
          <div className="field"><label>Project name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="field"><label>Compound</label>
            <input value={compound} onChange={(e) => setCompound(e.target.value)} /></div>
          <div className="field"><label>Question of interest</label>
            <textarea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} /></div>
          <button className="btn primary" disabled={busy} onClick={step1}>Create project</button>
        </Card>
      )}

      {step === 2 && (
        <Card title="2 · Compound Parameter Framework" action={<span className="muted">system of record</span>}>
          <p className="muted">The CPF every model is built from. Prefilled with a renal Aciclovir set (S0-complete:
            physchem + GFR elimination). Edit as JSON.</p>
          <div className="field">
            <textarea rows={16} value={cpfText} onChange={(e) => setCpfText(e.target.value)}
              style={{ fontFamily: "var(--mono, monospace)", fontSize: 12 }} />
          </div>
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => setStep(1)}>Back</button>
            <button className="btn primary" disabled={busy} onClick={step2}>Save CPF</button>
          </div>
        </Card>
      )}

      {step === 3 && (
        <Card title="3 · Observed studies">
          <p className="muted">Clinical studies with observed plasma profiles. The backend runs deterministic NCA
            (AUC, Cmax, tmax, t½) to get the observed PK the acceptance gate uses; the raw profile drives fitting.</p>
          <div className="field">
            <textarea rows={14} value={studiesText} onChange={(e) => setStudiesText(e.target.value)}
              style={{ fontFamily: "var(--mono, monospace)", fontSize: 12 }} />
          </div>
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => setStep(2)}>Back</button>
            <button className="btn primary" disabled={busy} onClick={step3}>Upload studies</button>
          </div>
        </Card>
      )}

      {step === 4 && (
        <Card title="4 · MAP and campaign">
          {!prep ? (
            <>
              <p className="muted">Generate the Model Analysis Plan from the CPF, studies and question. The study
                split (internal / external) and acceptance tier are computed deterministically.</p>
              <div className="row">
                <button className="btn" disabled={busy} onClick={() => setStep(3)}>Back</button>
                <button className="btn primary" disabled={busy} onClick={step4prepare}>Generate MAP</button>
              </div>
            </>
          ) : (
            <>
              <div className="banner ok" style={{ marginBottom: 12 }}>
                MAP generated — acceptance tier <strong>{prep.tier}</strong>, {prep.studies.length} study(ies).
              </div>
              <table>
                <thead><tr><th>Study</th><th>Assignment</th></tr></thead>
                <tbody>
                  {prep.studies.map((s) => (
                    <tr key={s.study_id}><td><code>{s.study_id}</code></td><td>{s.assignment}</td></tr>
                  ))}
                </tbody>
              </table>
              <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>
                Signing the MAP records a Part 11 electronic signature (loa2 step-up); the campaign then runs S0→S2
                on the single-node executor and this page opens the live monitor.
              </p>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" disabled={busy} onClick={() => setPrep(null)}>Back</button>
                <button className="btn primary" disabled={busy} onClick={signAndStart}>Sign MAP &amp; start campaign</button>
              </div>
            </>
          )}
        </Card>
      )}
    </main>
  );
}
