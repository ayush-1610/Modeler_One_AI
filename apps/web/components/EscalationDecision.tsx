"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { FeedbackDiagnosisView } from "@/components/campaign/Feedback";
import type { Escalation } from "@/lib/types";
import { resolveEscalation } from "@/lib/writes";

type Result = { kind: "ok" | "err"; message: string } | null;

export function EscalationDecision({ escalation }: { escalation: Escalation }) {
  const router = useRouter();
  const [choice, setChoice] = useState<string>("");
  const [rationale, setRationale] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result>(null);
  const fb = escalation.feedback;
  // learn: the failing studies whose class may learn are preselected; new evidence: one measured value
  const [studies, setStudies] = useState<string[]>(
    () => fb?.failing.filter((f) => fb.classes[f.class]?.learn.possible).map((f) => f.study_id) ?? []);
  const [beyondCap, setBeyondCap] = useState("");
  const [evidence, setEvidence] = useState({ parameter: "", value: "", unit: "", reference: "" });

  const option = escalation.options.find((o) => o.id === choice);
  const needsDeviation = choice === "learn" && fb
    ? studies.some((sid) => fb.classes[fb.failing.find((f) => f.study_id === sid)?.class ?? ""]?.learn.needs_deviation)
    : false;
  const evidenceValue = Number(evidence.value.replace(",", "."));
  const incomplete = choice === "learn" ? studies.length === 0 || (needsDeviation && !beyondCap.trim())
    : choice === "new_evidence" ? !evidence.parameter.trim() || !evidence.reference.trim() || !evidence.value.trim()
      || !Number.isFinite(evidenceValue)
    : false;

  async function submit() {
    setBusy(true);
    setResult(null);
    try {
      const res = await resolveEscalation(escalation.campaignId, escalation.stage, {
        action: choice as "retry" | "accept_best" | "abort" | "approve" | "learn" | "new_evidence",
        note: rationale,
        ...(choice === "learn" ? { studies, beyond_cap: beyondCap } : {}),
        ...(choice === "new_evidence" ? { evidence: { parameter: evidence.parameter.trim(), value: evidenceValue,
          unit: evidence.unit.trim() || null, reference: evidence.reference.trim() } } : {}),
      });
      if (!res.ok) {
        setResult({ kind: "err", message: res.detail ?? "The decision was rejected." });
        return;
      }
      setResult({
        kind: "ok",
        message: `Decision recorded — the campaign is now ${res.status ?? "updated"}.` +
          (res.signature ? ` Signed: ${res.signature.manifestation}` : ""),
      });
      router.refresh(); // the escalation is resolved; the inbox and monitor move on
    } catch {
      setResult({ kind: "err", message: "Could not reach the API to submit the decision." });
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <div>
      <div className="banner warn" style={{ marginBottom: 12 }}>
        <strong>{escalation.reasonCode}</strong> — {escalation.evidence}
      </div>
      {fb && <FeedbackDiagnosisView diagnosis={fb} />}

      <div className="field">
        <label>Decision</label>
        <select value={choice} onChange={(e) => setChoice(e.target.value)} data-testid="decision-select">
          <option value="">Select an option…</option>
          {escalation.options.map((o) => (
            <option key={o.id} value={o.id} disabled={!!o.disabled}>{o.label}{o.disabled ? " — not possible" : ""}</option>
          ))}
        </select>
        {escalation.options.filter((o) => o.disabled).map((o) => (
          <p key={o.id} className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>{o.label.split(":")[0]}: {o.disabled}</p>
        ))}
      </div>

      {choice === "learn" && fb && (
        <div className="field" data-testid="learn-form">
          <label>Studies to move to the internal set (a MAP deviation, signed with this decision)</label>
          {fb.failing.map((f) => {
            const cls = fb.classes[f.class];
            return (
              <label key={f.study_id} className="row" style={{ gap: 6, fontWeight: 400 }}>
                <input type="checkbox" disabled={!cls?.learn.possible} checked={studies.includes(f.study_id)}
                  onChange={(e) => setStudies((cur) => e.target.checked ? [...cur, f.study_id] : cur.filter((x) => x !== f.study_id))} />
                <code>{f.study_id}</code> trains {f.learn_stage}; then S5 judges {cls?.unspent.join(", ") || "nothing"}
              </label>
            );
          })}
          {needsDeviation && (
            <textarea rows={2} value={beyondCap} onChange={(e) => setBeyondCap(e.target.value)} data-testid="beyond-cap"
              placeholder="This class already had its learn cycle (D-05). Why another one is justified — recorded as a deviation." />
          )}
        </div>
      )}

      {choice === "new_evidence" && (
        <div className="field" data-testid="evidence-form">
          <label>The measured value (in the CPF&apos;s own unit; it replaces the parameter and is not fitted again)</label>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <input placeholder="CPF parameter id, e.g. phys.solubility.ref" value={evidence.parameter}
              onChange={(e) => setEvidence({ ...evidence, parameter: e.target.value })} data-testid="evidence-parameter" />
            <input placeholder="value" inputMode="decimal" value={evidence.value} style={{ width: 100 }}
              onChange={(e) => setEvidence({ ...evidence, value: e.target.value })} data-testid="evidence-value" />
            <input placeholder="unit" value={evidence.unit} style={{ width: 100 }}
              onChange={(e) => setEvidence({ ...evidence, unit: e.target.value })} data-testid="evidence-unit" />
          </div>
          <input placeholder="Source: the report or publication it was measured in" value={evidence.reference}
            onChange={(e) => setEvidence({ ...evidence, reference: e.target.value })} data-testid="evidence-reference"
            style={{ marginTop: 6 }} />
          <p className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>
            The whole chain re-runs from the new CPF and S5 re-judges the same studies; the report says the change was
            prompted by S5, and the verdict needs a model-risk review (D-06).
          </p>
        </div>
      )}

      <div className="field">
        <label>Rationale</label>
        <textarea rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)}
          placeholder="Recorded with the decision in the audit trail." />
      </div>

      <div className="row">
        <button className="btn primary" disabled={!choice || busy || incomplete} onClick={() => setConfirming(true)}
          data-testid="decision-sign">
          Sign &amp; submit
        </button>
        <span className="muted">Every decision is an approval and is signed (Part 11).</span>
      </div>

      {result && (
        <div className={`banner ${result.kind === "ok" ? "ok" : "err"}`} style={{ marginTop: 12 }}>
          {result.message}
        </div>
      )}

      {confirming && (
        <div role="dialog" aria-modal="true"
          style={{ position: "fixed", inset: 0, background: "rgba(10,15,22,0.45)", display: "grid", placeItems: "center", zIndex: 50 }}>
          <div className="card" style={{ maxWidth: 460 }}>
            <h2>Electronic signature</h2>
            <p className="muted">
              You are about to sign the decision <strong>{option?.label}</strong> for stage {escalation.stage} of
              campaign {escalation.campaignId}. This is recorded as an <em>Approved</em> signature bound to the
              decision; your password is never entered into Modeler One — the signature is taken from your
              session&apos;s step-up authentication.
            </p>
            <div className="row">
              <button className="btn primary" disabled={busy} onClick={() => void submit()} data-testid="decision-confirm">
                {busy ? "Submitting…" : "Sign & submit"}
              </button>
              <button className="btn" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
