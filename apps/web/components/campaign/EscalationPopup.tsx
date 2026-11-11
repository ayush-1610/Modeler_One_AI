"use client";

// A campaign waiting for a decision asks for it on whatever page the person is on (the owner's decision of 2026-11-11:
// "we handle these in place"; the review inbox is gone). Mounted once, in the root layout, over every open escalation
// of the tenant: it reads /api/v1/escalations itself, so it never depends on a campaign or project record being
// readable. The escalation of the campaign on screen comes first. "Decide later" closes the dialog for this visit and
// leaves a small "A decision is waiting · Open" control in the corner, on every page, until the decision is made; a
// reload asks again. The decision itself is the signed EscalationDecision (the signature comes from the step-up).

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { EscalationDecision } from "@/components/EscalationDecision";
import { Dialog } from "@/components/kit/Dialog";
import { narrow } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Escalation } from "@/lib/types";

const OPEN = "modeler:open-decision";

/** Open the waiting decision again after "Decide later" (the campaign page's feedback banner uses it). */
export function openDecision(campaignId?: string) {
  window.dispatchEvent(new CustomEvent(OPEN, { detail: campaignId ?? null }));
}

export function EscalationPopup() {
  const path = usePathname();
  const live = useResource("/api/v1/escalations", {}, { poll: () => true, interval: 5000 });
  const [later, setLater] = useState<string[]>([]);
  const [first, setFirst] = useState<string | null>(null);
  useEffect(() => {
    const reopen = (ev: Event) => { setFirst((ev as CustomEvent<string | null>).detail); setLater([]); };
    window.addEventListener(OPEN, reopen);
    return () => window.removeEventListener(OPEN, reopen);
  }, []);
  const campaign = /^\/campaigns\/([^/]+)/.exec(path)?.[1];
  const project = /^\/projects\/([^/]+)/.exec(path)?.[1]?.replace(/^start$/, "") || undefined;   // not the "Start from proposal" page
  // on a project's page, its own campaigns come first: read for the order only, so a list that cannot be read (one
  // stored campaign the API cannot answer with) changes the order, never whether a decision is asked
  const mine = useResource("/api/v1/campaigns", {}, { query: { project: project ? decodeURIComponent(project) : undefined },
                                                    select: (d) => d.campaigns.map((c) => c.id), enabled: Boolean(project) });
  const onScreen = first ? [first] : campaign ? [decodeURIComponent(campaign)] : project ? mine.data ?? [] : [];
  const open = (live.data?.escalations ?? []).map((e) => narrow<Escalation>(e));
  // the campaign on screen (or the one asked for) first, then the others in the order the API lists them
  const ordered = [...open.filter((e) => onScreen.includes(e.campaignId)), ...open.filter((e) => !onScreen.includes(e.campaignId))];
  const waiting = ordered.filter((e) => !later.includes(e.id));
  if (!open.length) return null;
  if (!waiting.length) {
    return (
      <div className="decision-waiting" role="status">
        <button type="button" className="btn primary" data-testid="escalation-waiting" onClick={() => openDecision()}>
          {open.length === 1 ? "A decision is waiting" : `${open.length} decisions are waiting`} · Open
        </button>
      </div>
    );
  }
  const e = waiting[0]!;
  const decideLater = () => { setLater([...later, ...waiting.map((w) => w.id)]); setFirst(null); };
  return (
    <Dialog title={`Your decision is needed: campaign ${e.campaignId}, stage ${e.stage}`} size="wide" testId="escalation-popup"
            onClose={decideLater}>
      {waiting.length > 1 && <p className="muted">{waiting.length - 1} more after this one.</p>}
      {/* keyed by the escalation: the next one opens with an empty form, never the last one's choice */}
      <EscalationDecision key={e.id} escalation={e} />
      <div className="dialog-actions">
        <button className="btn" onClick={decideLater} data-testid="escalation-later">Decide later</button>
      </div>
    </Dialog>
  );
}
