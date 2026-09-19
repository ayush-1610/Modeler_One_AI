"use client";

import { useState } from "react";

import { decideEscalation } from "@/lib/api";
import type { Escalation } from "@/lib/fixtures";

type Result = { kind: "ok" | "err"; message: string } | null;

export function EscalationDecision({ escalation }: { escalation: Escalation }) {
  const [choice, setChoice] = useState<string>("");
  const [rationale, setRationale] = useState("");
  const [steppingUp, setSteppingUp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result>(null);

  const option = escalation.options.find((o) => o.id === choice);
  const needsSignature = option?.requiresSignature ?? false;

  async function submit(signatureId?: string) {
    setBusy(true);
    setResult(null);
    try {
      // In production the loa2 step-up token comes from Keycloak (OIDC re-authentication); the app never
      // handles the password itself. Here we forward whatever bearer the session holds.
      const token = process.env.NEXT_PUBLIC_DEMO_TOKEN ?? "session";
      const env = await decideEscalation(
        escalation.campaignId,
        escalation.stage,
        { option_id: choice, rationale, signature_id: signatureId },
        token,
      );
      if (env.errors?.length) setResult({ kind: "err", message: env.errors[0].message });
      else setResult({ kind: "ok", message: `Decision '${choice}' submitted to the campaign workflow.` });
    } catch {
      setResult({ kind: "err", message: "Could not reach the API (start the backend to submit for real)." });
    } finally {
      setBusy(false);
      setSteppingUp(false);
    }
  }

  function onDecide() {
    if (!choice) return;
    if (needsSignature) setSteppingUp(true);
    else void submit();
  }

  return (
    <div>
      <div className="banner warn" style={{ marginBottom: 12 }}>
        <strong>{escalation.reasonCode}</strong> — {escalation.evidence}
      </div>

      <div className="field">
        <label>Decision</label>
        <select value={choice} onChange={(e) => setChoice(e.target.value)}>
          <option value="">Select an option…</option>
          {escalation.options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}{o.requiresSignature ? " (signature required)" : ""}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label>Rationale</label>
        <textarea rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)}
          placeholder="Recorded with the decision in the audit trail." />
      </div>

      <div className="row">
        <button className="btn primary" disabled={!choice || busy} onClick={onDecide}>
          {needsSignature ? "Sign & submit" : "Submit decision"}
        </button>
        {needsSignature && <span className="muted">Signed decisions require Keycloak re-authentication (loa2).</span>}
      </div>

      {result && (
        <div className={`banner ${result.kind === "ok" ? "ok" : "err"}`} style={{ marginTop: 12 }}>
          {result.message}
        </div>
      )}

      {steppingUp && (
        <div role="dialog" aria-modal="true"
          style={{ position: "fixed", inset: 0, background: "rgba(10,15,22,0.45)", display: "grid", placeItems: "center", zIndex: 50 }}>
          <div className="card" style={{ maxWidth: 420 }}>
            <h2>Electronic signature</h2>
            <p className="muted">
              You are about to sign the decision <strong>{option?.label}</strong> for stage {escalation.stage}.
              This requires step-up re-authentication with Keycloak; your password is never entered into Modeler One.
            </p>
            <div className="banner ok" style={{ marginBottom: 12 }}>
              Manifestation: <em>signer • {choice} • {new Date().toISOString().slice(0, 16).replace("T", " ")} UTC</em>
            </div>
            <div className="row">
              <button className="btn primary" disabled={busy}
                onClick={() => void submit("sig-step-up")}>Re-authenticate & sign</button>
              <button className="btn" disabled={busy} onClick={() => setSteppingUp(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
