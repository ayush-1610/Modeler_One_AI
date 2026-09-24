"use client";

import { useState } from "react";

import { prepareCampaign, signMap, startCampaign } from "@/lib/writes";

/**
 * One-click run of a project's modeling campaign: generate the MAP from the stored CPF + studies, sign it
 * (Part 11), start the campaign on the engine, then open the live monitor. This is the whole MS-01 entry
 * point for a project that already has its CPF and observed data loaded.
 */
export function RunCampaignButton({
  projectId,
  questionId,
  compound,
  stages,
}: {
  projectId: string;
  questionId: string;
  compound: string;
  /** Omit to run every MS-01 stage (the default): a stage without data is skipped with its reason. */
  stages?: string[];
}) {
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setStep("Generating the Model Analysis Plan…");
      const prep = await prepareCampaign(projectId, questionId, { compound, stages });
      if (prep.errors?.length || !prep.data) {
        setError(prep.errors?.[0]?.message ?? "Could not generate the MAP.");
        return;
      }
      setStep("Signing the MAP…");
      const signed = await signMap(projectId, { record_id: prep.data.map_id, record_sha256: prep.data.map_sha256 });
      if (!signed) {
        setError("The MAP signature was rejected (step-up required).");
        return;
      }
      setStep("Starting the campaign on the engine…");
      const started = await startCampaign(projectId, {
        compound,
        map_id: prep.data.map_id,
        cpf_uri: prep.data.cpf_uri,
        cpf_sha256: prep.data.cpf_sha256,
        map_uri: prep.data.map_uri,
        observed_uri: prep.data.observed_uri,
        model_risk: "medium",
        stages: prep.data.stages,
      });
      if (started.campaign_id) window.location.assign(`/campaigns/${started.campaign_id}`);
      else setError("The campaign did not start.");
    } catch {
      setError("Could not reach the API.");
    } finally {
      setBusy(false);
      setStep("");
    }
  }

  return (
    <div>
      <div className="row" style={{ alignItems: "center", gap: 10 }}>
        <button className="btn primary" disabled={busy} onClick={run}>
          {busy ? "Running…" : "Run campaign"}
        </button>
        {step && <span className="muted">{step}</span>}
      </div>
      {error && <div className="banner err" style={{ marginTop: 10 }}>{error}</div>}
    </div>
  );
}
