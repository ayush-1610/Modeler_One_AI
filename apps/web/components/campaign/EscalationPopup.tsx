"use client";

// A campaign waiting for a decision opens it right here, on the project or campaign page, instead of only in the
// review inbox (the owner's request, 2026-10-17). The inbox still lists every open escalation; "Decide later" closes
// this one until the page is opened again. The decision itself is the same signed decision as in the inbox.

import { useState } from "react";

import { EscalationDecision } from "@/components/EscalationDecision";
import { narrow } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Escalation } from "@/lib/types";

export function EscalationPopup({ campaignIds }: { campaignIds: string[] }) {
  const live = useResource("/api/v1/escalations", {}, { poll: () => campaignIds.length > 0, interval: 5000 });
  const [later, setLater] = useState<string[]>([]);
  const waiting = (live.data?.escalations ?? []).map((e) => narrow<Escalation>(e))
    .filter((e) => campaignIds.includes(e.campaignId) && !later.includes(e.id));
  if (!waiting.length) return null;
  const e = waiting[0];
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label={`Decision needed at ${e.stage}`}
         data-testid="escalation-popup">
      <div className="dialog" style={{ width: "min(760px, 100%)", maxHeight: "90vh", overflowY: "auto" }}>
        <h2 style={{ marginTop: 0 }}>Your decision is needed: campaign {e.campaignId}, stage {e.stage}</h2>
        {waiting.length > 1 && <p className="muted" style={{ marginTop: 0 }}>{waiting.length - 1} more after this one.</p>}
        <EscalationDecision escalation={e} />
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn" onClick={() => setLater([...later, e.id])} data-testid="escalation-later">Decide later</button>
        </div>
      </div>
    </div>
  );
}
