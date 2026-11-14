"use client";

// A campaign waiting for a decision asks for it in place (the review inbox is gone, 2026-11-11), scoped by the owner's
// decision of 2026-11-11 (docs/plans/2026-11-11-frontend-audit-2.md, decision 1): the dialog opens by itself only on the
// escalated campaign's own page and its project's pages; every other page (the dashboard, Start, the Library, another
// project) shows a small "N decisions waiting · Open" control in the corner, which opens the dialog on any page, so every
// escalation stays decidable from anywhere. Mounted once, in the root layout, over every open escalation of the tenant:
// it reads /api/v1/escalations itself, so it never depends on a campaign or project record being readable (a project
// page whose campaigns cannot be read shows the corner control, never a dialog it cannot place).
// "Decide later" holds for the rest of the browser tab's session: the put-off escalation ids are kept in sessionStorage,
// so a reload or a deep link in the same tab shows the corner control, not the dialog. An escalation that is no longer
// open is dropped from that list, so a new one (another stage) still asks. The decision itself is the signed
// EscalationDecision (the signature comes from the step-up); putting it off decides nothing.
// Nothing moves under the pointer: the dialog opens by itself only when a page is placed (it loads, or the person
// navigates to it), and then not while a pointer button is down, another dialog is open, or the person has already
// pressed a pointer or a key on this page; an escalation that arrives later, elsewhere, shows the corner control instead.
// Once open, the dialog stays on the escalation it shows until that one is decided or put off; one that arrives
// meanwhile is counted ("1 more after this one"), it never takes its place. Once decided, it stays on screen with the
// signed result (the signature's manifestation) until the person chooses "Next decision (n waiting)" or "Close"; the next
// decision, which may be another project's, never replaces it under the pointer by itself (the 2026-11-11 audit, item 5).
// The dialog says which project, compound and stage it asks about, links to the campaign's page (the goodness of fit and
// the rounds; following it puts the decision off), and warns when the campaign ran on a software fixture, not PK-Sim.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { EscalationDecision, type Decided } from "@/components/EscalationDecision";
import { Dialog } from "@/components/kit/Dialog";
import { narrow } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Escalation } from "@/lib/types";

const OPEN = "modeler:open-decision";
const LATER = "modeler:decide-later";

/** Open the waiting decision again after "Decide later" (the corner control and the campaign page's banner use it). */
export function openDecision(campaignId?: string) {
  window.dispatchEvent(new CustomEvent(OPEN, { detail: campaignId ?? null }));
}

// the escalation ids put off in this tab ("Decide later"); storage can be missing or refused (a private window, blocked
// site data), and then "Decide later" holds until the next full load only
function readLater(): string[] {
  try {
    const v: unknown = JSON.parse(window.sessionStorage.getItem(LATER) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch { return []; }
}
function writeLater(ids: readonly string[]) {
  try {
    if (ids.length) window.sessionStorage.setItem(LATER, JSON.stringify(ids));
    else window.sessionStorage.removeItem(LATER);
  } catch { /* not kept: see readLater */ }
}

// The escalations are read every 15 s; a running campaign's page, where a stage can stop for a decision at any moment,
// asks for 5 s while it is shown (<EscalationsExpected />, rendered by that page only while the campaign runs).
let expected = 0;
const listeners = new Set<() => void>();
const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
export function EscalationsExpected() {
  useEffect(() => {
    expected += 1; listeners.forEach((fn) => fn());
    return () => { expected -= 1; listeners.forEach((fn) => fn()); };
  }, []);
  return null;
}

export function EscalationPopup() {
  const path = usePathname();
  const often = useSyncExternalStore(subscribe, () => expected > 0, () => false);
  const live = useResource("/api/v1/escalations", {}, { poll: () => true, interval: often ? 5000 : 15_000 });
  // put off by the person ("Decide later"), kept for the tab's session
  const [later, setLater] = useState<string[]>(() => (typeof window === "undefined" ? [] : readLater()));
  const putOff = (ids: readonly string[]) => setLater((l) => { const next = [...new Set([...l, ...ids])]; writeLater(next); return next; });
  // shown in the corner on this page only, by the rule above (not the person's choice, so not kept)
  const [quiet, setQuiet] = useState<string[]>([]);
  const [first, setFirst] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  // the escalation being signed, held on screen from the moment it is sent (the open escalations are read again before
  // the answer returns, without it), and the signed result once recorded
  const [held, setHeld] = useState<Escalation | null>(null);
  const [recorded, setRecorded] = useState<Decided | null>(null);
  const corner = useRef<HTMLButtonElement>(null);
  const [toCorner, setToCorner] = useState(false);
  useEffect(() => {
    const reopen = (ev: Event) => {
      setFirst((ev as CustomEvent<string | null>).detail); setLater([]); writeLater([]); setQuiet([]); setPinned(null);
      setHeld(null); setRecorded(null);
    };
    window.addEventListener(OPEN, reopen);
    return () => window.removeEventListener(OPEN, reopen);
  }, []);
  // a pointer button held down (a drag on the canvas, a point being digitized): no dialog opens under it; and once the
  // person has pressed a pointer or a key on this page, a dialog arriving late would take that input, so none opens
  const down = useRef(false);
  const touched = useRef(false);
  useEffect(() => { touched.current = false; }, [path]);
  useEffect(() => {
    const press = () => { down.current = true; touched.current = true; };
    const release = () => { down.current = false; };
    const key = () => { touched.current = true; };
    window.addEventListener("pointerdown", press, true);
    window.addEventListener("pointerup", release, true);
    window.addEventListener("pointercancel", release, true);
    window.addEventListener("keydown", key, true);
    return () => {
      window.removeEventListener("pointerdown", press, true);
      window.removeEventListener("pointerup", release, true);
      window.removeEventListener("pointercancel", release, true);
      window.removeEventListener("keydown", key, true);
    };
  }, []);
  const campaign = /^\/campaigns\/([^/]+)/.exec(path)?.[1];
  const here = campaign ? decodeURIComponent(campaign) : null;
  const project = /^\/projects\/([^/]+)/.exec(path)?.[1]?.replace(/^start$/, "") || undefined;   // not the "Start from proposal" page
  // on a project's page, its own campaigns: their decisions are asked here, and come first. A list that cannot be read
  // (one stored campaign the API cannot answer with) asks nothing: its decisions go to the corner control.
  const mine = useResource("/api/v1/campaigns", {}, { query: { project: project ? decodeURIComponent(project) : undefined },
                                                    select: (d) => d.campaigns.map((c) => c.id), enabled: Boolean(project) });
  const onScreen = first ? [first] : here ? [here] : project ? mine.data ?? [] : [];
  const open = (live.data?.escalations ?? []).map((e) => narrow<Escalation>(e));
  // on a project's page the decisions to ask are known once its campaigns are read (or could not be): placing waits for it
  const orderReady = !project || mine.data !== null || mine.problem !== null;
  const asksHere = (e: Escalation) => e.campaignId === here || (project !== undefined && (mine.data ?? []).includes(e.campaignId));

  // drop the put-off ids that are no longer open (decided, or closed elsewhere), so a new escalation still asks
  const openIds = open.map((e) => e.id).join(" ");
  useEffect(() => {
    if (!live.data) return;
    const ids = new Set(openIds ? openIds.split(" ") : []);
    if (later.some((id) => !ids.has(id))) { const kept = later.filter((id) => ids.has(id)); setLater(kept); writeLater(kept); }
  }, [openIds, later, live.data]);

  // The escalations already placed on this page. When a page is placed (it loads, or the person goes to another page),
  // the open ones it asks for open in the dialog, unless the person is busy (above); the others go to the corner. One
  // that arrives later is placed here before it can show: while the dialog is open it joins the count; otherwise it goes
  // to the corner unless the person is on that campaign's page with no other dialog open and no pointer button down.
  const [known, setKnown] = useState<ReadonlySet<string> | null>(null);
  const [placedAt, setPlacedAt] = useState<string | null>(null);
  useEffect(() => {
    if (!live.data) return;
    const ids = openIds ? openIds.split(" ") : [];
    if (placedAt !== path) {
      if (!orderReady) return;
      setPlacedAt(path);
      if (pinned !== null) { setKnown(new Set([...(known ?? []), ...ids])); return; }   // a dialog already open stays as it is
      const busy = down.current || touched.current || document.querySelector(".dialog-backdrop") !== null;
      setKnown(new Set(ids));
      setQuiet(open.filter((e) => busy || !asksHere(e)).map((e) => e.id));
      return;
    }
    if (known === null) return;
    const fresh = open.filter((e) => !known.has(e.id));
    if (!fresh.length) return;
    setKnown(new Set([...known, ...fresh.map((e) => e.id)]));
    if (pinned !== null) return;
    const busy = down.current || document.querySelector(".dialog-backdrop") !== null;
    const toQuiet = fresh.filter((e) => busy || e.campaignId !== here).map((e) => e.id);
    if (toQuiet.length) setQuiet((q) => [...q, ...toQuiet]);
  }, [openIds, orderReady, known, pinned, path, placedAt]);   // eslint-disable-line react-hooks/exhaustive-deps

  // the campaign on screen (or the one asked for) first, then the others in the order the API lists them
  const ordered = [...open.filter((e) => onScreen.includes(e.campaignId)), ...open.filter((e) => !onScreen.includes(e.campaignId))];
  const placed = (e: Escalation) => known !== null && (known.has(e.id) || pinned !== null);
  const waiting = ordered.filter((e) => placed(e) && !later.includes(e.id) && !quiet.includes(e.id));
  // the escalation on screen stays until it is decided or put off: a later answer of the polls never puts another in its place
  // (one being signed, or just decided, stays until the person moves on)
  const shown = held ?? waiting.find((w) => w.id === pinned) ?? waiting[0] ?? null;
  useEffect(() => {
    if (shown ? shown.id !== pinned : pinned !== null) setPinned(shown?.id ?? null);
  }, [shown, pinned]);
  // the campaign it asks about and its project: their names for the title, and the engine its numbers came from. Read
  // one by one, so a campaign the API cannot answer for still asks, saying that its engine is not known.
  const campaignRead = useResource("/api/v1/campaigns/{campaign_id}", { campaign_id: shown?.campaignId ?? "" },
                                   { enabled: Boolean(shown) });
  const record = campaignRead.data && campaignRead.data.id === shown?.campaignId ? campaignRead.data : null;
  const projectRead = useResource("/api/v1/projects/{project_id}", { project_id: record?.project ?? "" },
                                  { enabled: Boolean(record) });
  const projectName = record && projectRead.data && projectRead.data.id === record.project ? projectRead.data.name : null;
  // after "Decide later", focus goes to the corner control that takes the dialog's place
  useEffect(() => { if (toCorner && corner.current) { corner.current.focus(); setToCorner(false); } }, [toCorner, shown]);
  // once a decision is recorded, focus is on "Close" (the form it was signed in is gone), never on the next decision
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (recorded) closeButton.current?.focus(); }, [recorded]);

  if (!held && (!open.length || known === null)) return null;
  if (!shown) {
    // a button in the tab order (right after the skip link: the layout renders it first), with the count; it opens the
    // dialog on whatever page this is
    return (
      <div className="decision-waiting" role="status">
        <button type="button" ref={corner} className="btn primary" data-testid="escalation-waiting" onClick={() => openDecision()}>
          {open.length === 1 ? "1 decision waiting" : `${open.length} decisions waiting`} · Open
        </button>
      </div>
    );
  }
  const e = shown;
  const others = waiting.filter((w) => w.id !== e.id);
  const decideLater = () => {
    putOff([e.id, ...others.map((w) => w.id)]); setFirst(null); setPinned(null); setHeld(null); setRecorded(null); setToCorner(true);
  };
  // after a decision: move on to the next one, or close and leave the others to the corner control on this page
  const moveOn = (next: boolean) => {
    setQuiet((q) => [...q, e.id, ...(next ? [] : others.map((w) => w.id))]);
    setHeld(null); setRecorded(null); setPinned(null); setFirst(null);
    if (!next) setToCorner(true);
  };
  const label = record?.stages.find((s) => s.stage === e.stage)?.label;
  const where = [projectName, `stage ${e.stage}${label && label !== e.stage ? ` (${label})` : ""}`].filter(Boolean).join(" · ");
  const idLine = (
    <p className="muted fs-12 decision-id" data-testid="escalation-campaign">
      Campaign <code>{e.campaignId}</code>{record ? ` · ${record.compound}` : ""} ·{" "}
      <Link href={`/campaigns/${encodeURIComponent(e.campaignId)}`} data-testid="escalation-see-campaign"
            onClick={() => (recorded ? moveOn(false) : decideLater())}>See the campaign</Link>
    </p>
  );
  if (recorded) {
    return (
      <Dialog title={`Decision recorded · ${where}`} size="wide" testId="escalation-popup" onClose={() => moveOn(false)}>
        {idLine}
        <div className="banner ok" role="status" data-testid="decision-recorded">
          Decision recorded — the campaign is now {recorded.status ?? "updated"}.
          {recorded.manifestation && <><br />Signed: <strong>{recorded.manifestation}</strong></>}
        </div>
        <div className="dialog-actions">
          <button ref={closeButton} className="btn" onClick={() => moveOn(false)} data-testid="escalation-close">Close</button>
          {others.length > 0 && (
            <button className="btn primary" onClick={() => moveOn(true)} data-testid="escalation-next">
              Next decision ({others.length} waiting)
            </button>
          )}
        </div>
      </Dialog>
    );
  }
  return (
    <Dialog title={`Your decision is needed · ${where}`} size="wide" testId="escalation-popup" onClose={decideLater}>
      {idLine}
      {others.length > 0 && <p className="muted">{others.length} more after this one.</p>}
      {/* keyed by the escalation: the next one opens with an empty form, never the last one's choice */}
      <EscalationDecision key={e.id} escalation={e} engine={record?.engine ?? null}
                          engineUnknown={record ? null : campaignRead.problem}
                          onSubmit={() => setHeld(e)} onDecided={setRecorded}
                          actions={<button className="btn" onClick={decideLater} data-testid="escalation-later">Decide later</button>} />
    </Dialog>
  );
}
