"use client";

import { openDecision } from "@/components/campaign/EscalationPopup";

/** Opens this campaign's waiting decision again after "Decide later" (the pop-up in the root layout holds it). */
export function OpenDecisionButton({ campaignId }: { campaignId: string }) {
  return (
    <button type="button" className="btn primary" data-testid="open-decision" onClick={() => openDecision(campaignId)}>
      Open the decision
    </button>
  );
}
