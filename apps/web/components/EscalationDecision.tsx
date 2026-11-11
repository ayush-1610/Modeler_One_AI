"use client";

import { useId, useState, type ReactNode } from "react";

import { EngineWarning } from "@/components/campaign/EngineWarning";
import { FeedbackDiagnosisView } from "@/components/campaign/Feedback";
import { Dialog } from "@/components/kit/Dialog";
import { useMutation } from "@/lib/hooks";
import { reasonSentence } from "@/lib/reason";
import type { EngineIdentity, Escalation } from "@/lib/types";
import { resolveEscalation } from "@/lib/writes";
import { celebrate, toast } from "@/components/kit/Motion";
import { Banner } from "@/components/kit";

type Result = { kind: "ok" | "err"; message: string } | null;

/** A signed decision, as the API answered it: what the campaign is now and the signature's manifestation. */
export type Decided = { status: string | null; manifestation: string | null };

export function EscalationDecision({ escalation, engine, engineUnknown, actions, onSubmit, onDecided }: {
  escalation: Escalation;
  /** What produced the campaign's numbers; a decision over a software fixture's numbers says so (CLAUDE.md). */
  engine?: EngineIdentity | null;
  /** Why the campaign record (and so its engine) could not be read; said instead of the engine. */
  engineUnknown?: string | null;
  /** The other buttons of the action row ("Decide later"), before "Sign & submit". */
  actions?: ReactNode;
  /** Called when the signed decision is sent, and when the API has recorded it (the pop-up keeps the result on screen). */
  onSubmit?: () => void;
  onDecided?: (decided: Decided) => void;
}) {
  const ids = useId();
  const { run, busy } = useMutation();
  const [choice, setChoice] = useState<string>("");
  const [rationale, setRationale] = useState("");
  const [confirming, setConfirming] = useState(false);
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
  // what is missing, said next to the disabled "Sign & submit"
  const missing = !choice ? "Choose a decision first."
    : choice === "learn" ? (studies.length === 0 ? "Choose at least one study to move."
      : needsDeviation && !beyondCap.trim() ? "Say why another learn cycle is justified." : null)
    : choice === "new_evidence" && incomplete
      ? (evidence.value.trim() && !Number.isFinite(evidenceValue) ? "The value must be a number."
        : "Fill in the parameter, the value and its source.")
    : null;

  async function submit() {
    setResult(null);
    onSubmit?.();
    // a signed decision, then the open escalations and the monitor (server-rendered) read again
    const { data, problem } = await run(() => resolveEscalation(escalation.campaignId, escalation.stage, {
        action: choice as "retry" | "accept_best" | "abort" | "approve" | "learn" | "new_evidence",
        note: rationale,
        ...(choice === "learn" ? { studies, beyond_cap: beyondCap } : {}),
        ...(choice === "new_evidence" ? { evidence: { parameter: evidence.parameter.trim(), value: evidenceValue,
          unit: evidence.unit.trim() || null, reference: evidence.reference.trim() } } : {}),
    }));
    setConfirming(false);
    if (!data) {
      setResult({ kind: "err", message: problem ?? "The decision was rejected." });
      return;
    }
    const message = `Decision recorded — the campaign is now ${data.status ?? "updated"}.` +
      (data.signature ? ` Signed: ${data.signature.manifestation}` : "");
    setResult({ kind: "ok", message });
    onDecided?.({ status: data.status ?? null, manifestation: data.signature?.manifestation ?? null });
    if (data.signature) celebrate();
    toast(`Decision recorded — the campaign is now ${data.status ?? "updated"}.`);
  }

  return (
    <div>
      <EngineWarning engine={engine} testId="decision-engine-warning" className="mb-12" />
      {engineUnknown && (
        <div className="banner warn mb-12" role="note" data-testid="decision-engine-unknown">
          The campaign record could not be read ({engineUnknown}), so the engine its numbers came from is not known.
          See the campaign before you decide.
        </div>
      )}
      <Banner tone="warn" className="mb-12">
        <strong title={escalation.reasonCode}>{reasonSentence(escalation.reasonCode)}</strong> — {escalation.evidence}
      </Banner>
      {fb && <FeedbackDiagnosisView diagnosis={fb} />}

      <div className="field">
        <label htmlFor={`${ids}-decision`}>Decision</label>
        <select id={`${ids}-decision`} value={choice} onChange={(e) => setChoice(e.target.value)} data-testid="decision-select">
          <option value="">Select an option…</option>
          {escalation.options.map((o) => (
            <option key={o.id} value={o.id} disabled={!!o.disabled}>{o.label}{o.disabled ? " — not possible" : ""}</option>
          ))}
        </select>
        {escalation.options.filter((o) => o.disabled).map((o) => (
          <p key={o.id} className="muted fs-12 m-4-0-0">{o.label.split(":")[0]}: {o.disabled}</p>
        ))}
      </div>

      {choice === "learn" && fb && (
        <div className="field" data-testid="learn-form">
          <label>Studies to move to the internal set (a MAP deviation, signed with this decision)</label>
          {fb.failing.map((f) => {
            const cls = fb.classes[f.class];
            return (
              <label key={f.study_id} className="row gap-6 fw-400">
                <input type="checkbox" disabled={!cls?.learn.possible} checked={studies.includes(f.study_id)}
                  onChange={(e) => setStudies((cur) => e.target.checked ? [...cur, f.study_id] : cur.filter((x) => x !== f.study_id))} />
                <code>{f.study_id}</code> trains {f.learn_stage}; then S5 judges {cls?.unspent.join(", ") || "nothing"}
              </label>
            );
          })}
          {needsDeviation && (
            <textarea rows={2} value={beyondCap} aria-label="Why another learn cycle is justified" onChange={(e) => setBeyondCap(e.target.value)} data-testid="beyond-cap"
              placeholder="This class already had its learn cycle. Why another one is justified — recorded as a deviation." />
          )}
        </div>
      )}

      {choice === "new_evidence" && (
        <div className="field" data-testid="evidence-form">
          <p className="field-legend m-0-0-6">The measured value (in the CPF&apos;s own unit; it replaces the parameter and is not fitted again)</p>
          <div className="row gap-6 flex-wrap evidence-fields">
            <label htmlFor={`${ids}-parameter`} className="fw-400">Parameter
              <input id={`${ids}-parameter`} placeholder="CPF parameter id, e.g. phys.solubility.ref" value={evidence.parameter}
                onChange={(e) => setEvidence({ ...evidence, parameter: e.target.value })} data-testid="evidence-parameter" /></label>
            <label htmlFor={`${ids}-value`} className="fw-400">Value
              <input id={`${ids}-value`} inputMode="decimal" value={evidence.value}
                onChange={(e) => setEvidence({ ...evidence, value: e.target.value })} data-testid="evidence-value" /></label>
            <label htmlFor={`${ids}-unit`} className="fw-400">Unit
              <input id={`${ids}-unit`} value={evidence.unit}
                onChange={(e) => setEvidence({ ...evidence, unit: e.target.value })} data-testid="evidence-unit" /></label>
          </div>
          <label htmlFor={`${ids}-source`} className="fw-400 mt-6">Source
            <input id={`${ids}-source`} placeholder="the report or publication it was measured in" value={evidence.reference}
              onChange={(e) => setEvidence({ ...evidence, reference: e.target.value })} data-testid="evidence-reference" /></label>
          <p className="muted fs-12 m-4-0-0">
            The whole chain re-runs from the new CPF and S5 re-judges the same studies; the report says the change was
            prompted by S5, and the verdict needs a model-risk review.
          </p>
        </div>
      )}

      <div className="field">
        <label htmlFor={`${ids}-rationale`}>Rationale</label>
        <textarea id={`${ids}-rationale`} rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)}
          placeholder="Recorded with the decision in the audit trail." />
      </div>

      <p className="muted fs-12">Every decision is an approval and is signed (Part 11).</p>

      {result && (
        <div className={`banner ${result.kind === "ok" ? "ok" : "err"} mb-12`} role={result.kind === "ok" ? "status" : "alert"}>
          {result.message}
        </div>
      )}

      {/* "Decide later" on the left, the signed decision on the right; what is missing is named beside it */}
      <div className="dialog-actions">
        {!busy && missing && <span className="muted fs-12 decision-missing" data-testid="decision-missing">{missing}</span>}
        {actions}
        <button className="btn primary" disabled={!choice || busy || incomplete} onClick={() => setConfirming(true)}
          data-testid="decision-sign">
          Sign &amp; submit
        </button>
      </div>

      {confirming && (
        <Dialog title="Electronic signature" size="narrow" testId="decision-confirm-dialog"
                onClose={() => { if (!busy) setConfirming(false); }}>
          <>
            <p className="muted">
              You are about to sign the decision <strong>{option?.label}</strong> for stage {escalation.stage} of
              campaign {escalation.campaignId}. This is recorded as an <em>Approved</em> signature bound to the
              decision; your password is never entered into Modeler One — the signature is taken from your
              session&apos;s step-up authentication.
            </p>
            <div className="dialog-actions">
              <button className="btn" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
              <button className="btn primary" disabled={busy} onClick={() => void submit()} data-testid="decision-confirm">
                {busy ? "Submitting…" : "Sign & submit"}
              </button>
            </div>
          </>
        </Dialog>
      )}
    </div>
  );
}
