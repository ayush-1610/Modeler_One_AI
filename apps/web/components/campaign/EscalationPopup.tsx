"use client";

// A campaign waiting for a decision asks for it on whatever page the person is on (the owner's decision of 2026-11-11:
// "we handle these in place"; the review inbox is gone). Mounted once, in the root layout, over every open escalation
// of the tenant: it reads /api/v1/escalations itself, so it never depends on a campaign or project record being
// readable. The escalation of the campaign on screen comes first. "Decide later" closes the dialog for this visit and
// leaves a small "A decision is waiting · Open" control in the corner, on every page, until the decision is made; a
// reload asks again. The decision itself is the signed EscalationDecision (the signature comes from the step-up).
// Nothing moves under the pointer: the dialog opens by itself only when a page loads (or on the campaign's own page, and
// then not while another dialog is open or a pointer button is down); an escalation that arrives later, elsewhere, shows
// the corner control instead. Once open, the dialog stays on the escalation it shows until that one is decided or put
// off; one that arrives meanwhile is counted ("1 more after this one"), it never takes its place.

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

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
  const [pinned, setPinned] = useState<string | null>(null);
  const corner = useRef<HTMLButtonElement>(null);
  const [toCorner, setToCorner] = useState(false);
  useEffect(() => {
    const reopen = (ev: Event) => { setFirst((ev as CustomEvent<string | null>).detail); setLater([]); setPinned(null); };
    window.addEventListener(OPEN, reopen);
    return () => window.removeEventListener(OPEN, reopen);
  }, []);
  // a pointer button held down (a drag on the canvas, a point being digitized): no dialog opens under it
  const down = useRef(false);
  useEffect(() => {
    const press = () => { down.current = true; };
    const release = () => { down.current = false; };
    window.addEventListener("pointerdown", press, true);
    window.addEventListener("pointerup", release, true);
    window.addEventListener("pointercancel", release, true);
    return () => {
      window.removeEventListener("pointerdown", press, true);
      window.removeEventListener("pointerup", release, true);
      window.removeEventListener("pointercancel", release, true);
    };
  }, []);
  const campaign = /^\/campaigns\/([^/]+)/.exec(path)?.[1];
  const project = /^\/projects\/([^/]+)/.exec(path)?.[1]?.replace(/^start$/, "") || undefined;   // not the "Start from proposal" page
  // on a project's page, its own campaigns come first: read for the order only, so a list that cannot be read (one
  // stored campaign the API cannot answer with) changes the order, never whether a decision is asked
  const mine = useResource("/api/v1/campaigns", {}, { query: { project: project ? decodeURIComponent(project) : undefined },
                                                    select: (d) => d.campaigns.map((c) => c.id), enabled: Boolean(project) });
  const onScreen = first ? [first] : campaign ? [decodeURIComponent(campaign)] : project ? mine.data ?? [] : [];
  const open = (live.data?.escalations ?? []).map((e) => narrow<Escalation>(e));
  // on a project's page the order is known once its campaigns are read (or could not be): the first dialog waits for it
  const orderReady = !project || mine.data !== null || mine.problem !== null;

  // The escalations already placed. The ones open when the page loads are asked in the dialog. One that arrives later is
  // placed here before it can show: while the dialog is open it joins the count; otherwise it goes to the corner (as if
  // put off) unless the person is on that campaign's page with no other dialog open and no pointer button down.
  const [known, setKnown] = useState<ReadonlySet<string> | null>(null);
  const openIds = open.map((e) => e.id).join(" ");
  useEffect(() => {
    if (!live.data) return;
    const ids = openIds ? openIds.split(" ") : [];
    if (known === null) { if (orderReady) setKnown(new Set(ids)); return; }
    const fresh = open.filter((e) => !known.has(e.id));
    if (!fresh.length) return;
    setKnown(new Set([...known, ...fresh.map((e) => e.id)]));
    if (pinned !== null) return;
    const busy = down.current || document.querySelector(".dialog-backdrop") !== null;
    const here = campaign ? decodeURIComponent(campaign) : null;
    const quiet = fresh.filter((e) => busy || e.campaignId !== here).map((e) => e.id);
    if (quiet.length) setLater((l) => [...l, ...quiet]);
  }, [openIds, orderReady, known, pinned]);   // eslint-disable-line react-hooks/exhaustive-deps

  // the campaign on screen (or the one asked for) first, then the others in the order the API lists them
  const ordered = [...open.filter((e) => onScreen.includes(e.campaignId)), ...open.filter((e) => !onScreen.includes(e.campaignId))];
  const placed = (e: Escalation) => known !== null && (known.has(e.id) || pinned !== null);
  const waiting = ordered.filter((e) => placed(e) && !later.includes(e.id));
  // the escalation on screen stays until it is decided or put off: a later answer of the polls never puts another in its place
  const shown = waiting.find((w) => w.id === pinned) ?? waiting[0] ?? null;
  useEffect(() => {
    if (shown ? shown.id !== pinned : pinned !== null) setPinned(shown?.id ?? null);
  }, [shown, pinned]);
  // after "Decide later", focus goes to the corner control that takes the dialog's place
  useEffect(() => { if (toCorner && corner.current) { corner.current.focus(); setToCorner(false); } }, [toCorner, shown]);

  if (!open.length || known === null) return null;
  if (!shown) {
    return (
      <div className="decision-waiting" role="status">
        <button type="button" ref={corner} className="btn primary" data-testid="escalation-waiting" onClick={() => openDecision()}>
          {open.length === 1 ? "A decision is waiting" : `${open.length} decisions are waiting`} · Open
        </button>
      </div>
    );
  }
  const e = shown;
  const decideLater = () => { setLater([...later, ...waiting.map((w) => w.id)]); setFirst(null); setPinned(null); setToCorner(true); };
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
