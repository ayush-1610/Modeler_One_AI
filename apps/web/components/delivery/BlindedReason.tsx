"use client";

// Why a study is blinded until the plan is signed (D-15), said where it is withheld, with the part of the reason that can
// be changed leading to where it is changed (final review round 5): "it is entered for external validation on its card"
// to the study's purpose on its delivery card (`onPurpose`: the card that shows the reason says how to bring that fact
// into view, opening the delivery's reading first where it is folded), "the plan places it in S5 …" and "the study split
// proposes it for S5 …" to the plan's studies and roles on Review & sign. The rest is said as it is (`blindedParts`).

import Link from "next/link";
import { Fragment } from "react";

import { blindedParts } from "@/lib/inputsWork";

/** The plan's studies and roles, where a study's role is decided (Review & sign). */
export const rolesHref = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/plan#review-studies`;

export function BlindedReason({ why, projectId, onPurpose, whose, testId }: {
  why: string; projectId: string;
  /** bring the study's purpose on its delivery card into view; absent, that part is said, not linked */
  onPurpose?: () => void;
  /** the study in words ("study 231-24"), for the link's name */
  whose?: string;
  testId?: string;
}) {
  return (
    <span data-testid={testId}>
      {blindedParts(why).map((part, i) => (part.to === "purpose" && onPurpose
        ? <button key={i} type="button" className="link-btn" onClick={onPurpose} data-testid={testId ? `${testId}-purpose` : undefined}
                  aria-label={`${part.text}: open the purpose${whose ? ` of ${whose}` : ""} on its card, to change it`}>{part.text}</button>
        : part.to === "plan"
          ? <Link key={i} href={rolesHref(projectId)} prefetch={false} data-testid={testId ? `${testId}-plan` : undefined}
                  aria-label={`${part.text}: the studies and their roles, on Review & sign`}>{part.text}</Link>
          : <Fragment key={i}>{part.text}</Fragment>))}
    </span>
  );
}

/** Bring a place on the page into view and give it the focus once it is drawn (a fold opened, a card read): tried for a
 *  few seconds, then given up. */
export function focusWhenDrawn(testId: string) {
  let tries = 0;
  const go = () => {
    const el = document.querySelector<HTMLElement>(`[data-testid="${CSS.escape(testId)}"]`);
    if (!el) { if (++tries < 60) window.setTimeout(go, 100); return; }
    for (let fold = el.closest("details"); fold; fold = fold.parentElement?.closest("details") ?? null) if (!fold.open) fold.open = true;
    el.scrollIntoView({ block: "center" });
    el.focus({ preventScroll: true });
    el.classList.add("just-opened");
    window.setTimeout(() => el.classList.remove("just-opened"), 1600);
  };
  window.setTimeout(go, 50);
}
