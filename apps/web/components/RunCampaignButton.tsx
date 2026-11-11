"use client";

import { useState } from "react";

import { Banner } from "@/components/kit";
import { startCampaign } from "@/lib/writes";

type CampaignBody = Parameters<typeof startCampaign>[1];

/**
 * The one start of a project's modeling campaign: the campaign starts from the MAP signed on Review & sign, with the
 * inputs that signature staged (the MAP artifact's `campaign`), then the live monitor opens. Nothing is generated or
 * signed here (the owner's decision 2 of 2026-11-11): the one review and the one signature are on Review & sign.
 */
export function RunCampaignButton({ projectId, campaign }: {
  projectId: string;
  /** The signed MAP's staged campaign inputs, as plan:sign stored them (stored content, read on the server). */
  campaign: Record<string, unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const started = await startCampaign(projectId, campaign as CampaignBody);
      if (started.campaign_id) {
        window.location.assign(`/campaigns/${started.campaign_id}`);
        return;
      }
      setError(`The campaign did not start: ${started.error ?? "no campaign id returned"}`);
    } catch {
      setError("Could not reach the API.");
    }
    setBusy(false);
  }

  return (
    <div>
      <div className="row items-center gap-10">
        <button className="btn primary" disabled={busy} onClick={run} data-testid="run-campaign">
          {busy ? "Starting…" : "Run campaign"}
        </button>
        {busy && <span className="muted">Starting the campaign on the engine…</span>}
      </div>
      {error && <div className="mt-10"><Banner tone="err" testId="run-error">{error}</Banner></div>}
    </div>
  );
}
