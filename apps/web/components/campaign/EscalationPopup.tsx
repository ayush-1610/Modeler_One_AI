"use client";

// A campaign waiting for a decision (the console redesign, slice 2; design-review/PRODUCT_SITEMAP.md "Escalation
// notice"): on that campaign's project pages and on the campaign's own page, a flash bar says a decision is waiting, for
// the people who may take it (the API's `can_decide`, R-S02), and the signed decision opens from it. Your work lists the
// same decision as a link. It no longer opens by itself on every page: nothing appears over what a person is doing.
//
// Mounted once in the shell, over the open escalations: it reads /api/v1/escalations itself, so an escalation whose
// campaign is not recorded yet is still asked on that campaign's page (Your work links there). While the dialog is open
// and a decision on this page is taken, the next one of this page is asked in the same place (an S5 decision, then the
// S4/S5 evaluation's signature). The decision itself is the signed EscalationDecision (the signature from the step-up).

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { EscalationDecision } from "@/components/EscalationDecision";
import { Dialog } from "@/components/kit/Dialog";
import { Icon } from "@/components/kit/icons";
import { narrow } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Escalation } from "@/lib/types";

const OPEN = "modeler:open-decision";

/** Open the waiting decision (the campaign page's feedback banner uses it). */
export function openDecision(campaignId?: string) {
  window.dispatchEvent(new CustomEvent(OPEN, { detail: campaignId ?? null }));
}

const said = (code: string) => code.replace(/_/g, " ").toLowerCase();

export function EscalationPopup() {
  const path = usePathname();
  const live = useResource("/api/v1/escalations", {}, { poll: () => true, interval: 5000 });
  const campaign = /^\/campaigns\/([^/]+)/.exec(path)?.[1];
  const projectMatch = /^\/projects\/([^/]+)/.exec(path)?.[1];
  const project = projectMatch && projectMatch !== "start" ? decodeURIComponent(projectMatch) : null;
  // which project each campaign belongs to: read only on a project's pages
  const owners = useResource("/api/v1/campaigns", {}, { enabled: Boolean(project), select: (d) => new Map(d.campaigns.map((c) => [c.id, c.project])) });
  const [asked, setAsked] = useState<{ prefer: string | null } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const [refocus, setRefocus] = useState(false);

  const open = (live.data?.escalations ?? []).filter((e) => e.can_decide).map((e) => narrow<Escalation>(e));
  const here = open.filter((e) => (campaign ? e.campaignId === decodeURIComponent(campaign)
    : project ? owners.data?.get(e.campaignId) === project : false));

  useEffect(() => {
    const reopen = (ev: Event) => setAsked({ prefer: (ev as CustomEvent<string | null>).detail });
    window.addEventListener(OPEN, reopen);
    return () => window.removeEventListener(OPEN, reopen);
  }, []);
  useEffect(() => { setAsked(null); }, [path]);
  useEffect(() => { if (refocus) { button.current?.focus(); setRefocus(false); } }, [refocus]);

  // the one asked for, else the first of this page's; when it is decided, the next of this page's in the same place
  const pool = asked?.prefer ? [...here.filter((e) => e.campaignId === asked.prefer), ...here.filter((e) => e.campaignId !== asked.prefer)] : here;
  const shown = asked ? pool[0] ?? null : null;
  useEffect(() => { if (asked && live.data && here.length === 0) setAsked(null); }, [asked, live.data, here.length]);

  if (here.length === 0) return null;
  const first = here[0]!;
  const close = () => { setAsked(null); setRefocus(true); };
  return (
    <>
      <div className="flash shell-flash" role="status" data-testid="escalation-flash">
        <Icon name="alert" />
        <span className="flash-text">
          <strong>{here.length === 1 ? "A decision is waiting." : `${here.length} decisions are waiting.`}</strong>{" "}
          Campaign <code>{first.campaignId}</code>, stage {first.stage}: {said(first.reasonCode)}.
        </span>
        <button type="button" ref={button} className="btn" data-testid="escalation-waiting" onClick={() => setAsked({ prefer: null })}>
          Decide
        </button>
      </div>
      {shown && (
        <Dialog title={`Your decision is needed: campaign ${shown.campaignId}, stage ${shown.stage}`} size="wide" testId="escalation-popup"
                onClose={close}>
          {here.length > 1 && <p className="muted">{here.length - 1} more after this one.</p>}
          {/* keyed by the escalation: the next one opens with an empty form, never the last one's choice */}
          <EscalationDecision key={shown.id} escalation={shown} />
          <div className="dialog-actions">
            <button className="btn" onClick={close} data-testid="escalation-later">Decide later</button>
          </div>
        </Dialog>
      )}
    </>
  );
}
