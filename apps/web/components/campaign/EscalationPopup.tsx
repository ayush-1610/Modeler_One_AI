"use client";

// A campaign waiting for a decision opens it right here, on the project or campaign page, instead of only in the
// review inbox (the owner's request, 2026-10-17). The inbox still lists every open escalation; "Decide later" closes
// this one until the page is opened again. The decision itself is the same signed decision as in the inbox.

import { useState } from "react";

import { EscalationDecision } from "@/components/EscalationDecision";
import { Dialog } from "@/components/kit/Dialog";
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
  const decideLater = () => setLater([...later, e.id]);
  return (
    <Dialog title={`Your decision is needed: campaign ${e.campaignId}, stage ${e.stage}`} size="wide" testId="escalation-popup"
            onClose={decideLater}>
      {waiting.length > 1 && <p className="muted">{waiting.length - 1} more after this one.</p>}
      <EscalationDecision escalation={e} />
      <div className="dialog-actions">
        <button className="btn" onClick={decideLater} data-testid="escalation-later">Decide later</button>
      </div>
    </Dialog>
  );
}
