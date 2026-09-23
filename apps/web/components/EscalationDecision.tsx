"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { Escalation } from "@/lib/fixtures";
import { resolveEscalation } from "@/lib/writes";

type Result = { kind: "ok" | "err"; message: string } | null;

export function EscalationDecision({ escalation }: { escalation: Escalation }) {
  const router = useRouter();
  const [choice, setChoice] = useState<string>("");
  const [rationale, setRationale] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result>(null);

  const option = escalation.options.find((o) => o.id === choice);

  async function submit() {
    setBusy(true);
    setResult(null);
    try {
      const res = await resolveEscalation(escalation.campaignId, escalation.stage, {
        action: choice as "retry" | "accept_best" | "abort",
        note: rationale,
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

      <div className="field">
        <label>Decision</label>
        <select value={choice} onChange={(e) => setChoice(e.target.value)}>
          <option value="">Select an option…</option>
          {escalation.options.map((o) => (
            <option key={o.id} value={o.id}>{o.label}</option>
          ))}
        </select>
      </div>

      <div className="field">
        <label>Rationale</label>
        <textarea rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)}
          placeholder="Recorded with the decision in the audit trail." />
      </div>

      <div className="row">
        <button className="btn primary" disabled={!choice || busy} onClick={() => setConfirming(true)}>
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
              <button className="btn primary" disabled={busy} onClick={() => void submit()}>
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
