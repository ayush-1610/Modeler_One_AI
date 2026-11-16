"use client";

// Why a study is blinded until the plan is signed (D-15), said where it is withheld, with the part of the reason that can
// be changed leading to where it is changed (final review round 5): "it is entered for external validation on its card"
// to the study's purpose on its delivery card (`onPurpose`: the card that shows the reason says how to bring that fact
// into view, opening the delivery's reading first where it is folded), "the plan places it in S5 …" and "the study split
// proposes it for S5 …" to the plan's studies and roles on Review & sign, while Review & sign can show them (round 6:
// before the inputs are ready it shows only that it opens once they are, so the part is said, with what it waits on). The
// rest is said as it is (`blindedParts`).

import Link from "next/link";
import { createContext, Fragment, useContext } from "react";

import { blindedParts } from "@/lib/inputsWork";
import { inputsHref } from "@/lib/words";

/** The plan's studies and roles, where a study's role is decided (Review & sign). */
export const rolesHref = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/plan#review-studies`;

/** Where a blinded reason may lead, as the page knows it (round 6), given by the page that shows the reasons (Inputs):
 *  `roles`, Review & sign can show its studies and roles now (the plan is made from ready inputs, the API's
 *  `inputs_ready`: the inputs are ready and were checked since they last changed); `purpose`, the signed-in person may
 *  change the purpose that blinds a study, as their roles allow the blinding to be set (PUT /blinding: the MIDD lead's,
 *  modeler-reviewer). Elsewhere neither: the parts are said, and "Change the purpose…" is not offered. */
export type Reach = { roles: boolean; purpose: boolean };
export const ReachContext = createContext<Reach>({ roles: false, purpose: false });
/** The roles that may set the project's blinding (the API's PUT /blinding), so change the purpose that blinds a study. */
export const BLINDING_ROLES = ["modeler-reviewer"];

export function BlindedReason({ why, projectId, onPurpose, whose, testId }: {
  why: string; projectId: string;
  /** bring the study's purpose on its delivery card into view; absent, that part is said, not linked */
  onPurpose?: () => void;
  /** the study in words ("study 231-24"), for the link's name */
  whose?: string;
  testId?: string;
}) {
  const reach = useContext(ReachContext);
  return (
    <span data-testid={testId}>
      {blindedParts(why).map((part, i) => (part.to === "purpose" && onPurpose
        ? <button key={i} type="button" className="link-btn" onClick={onPurpose} data-testid={testId ? `${testId}-purpose` : undefined}
                  aria-label={`${part.text}: open the purpose${whose ? ` of ${whose}` : ""} on its card${reach.purpose ? ", to change it" : ""}`}>
            {part.text}</button>
        : part.to === "plan" && reach.roles
          ? <Link key={i} href={rolesHref(projectId)} prefetch={false} data-testid={testId ? `${testId}-plan` : undefined}
                  aria-label={`${part.text}: the studies and their roles, on Review & sign`}>{part.text}</Link>
          : part.to === "plan"
            // Review & sign shows only that it opens once the inputs are ready: the part is said, with what it waits on (the
            // step bar's "Waiting on you", the reasons Review & sign lists, with To do below it)
            ? <Fragment key={i}>{part.text}<span className="muted" data-testid={testId ? `${testId}-plan-waits` : "blinded-plan-waits"}>
                {" "}(its role is decided on Review &amp; sign, which opens once the inputs are ready:{" "}
                <Link href={inputsHref(projectId, { area: "todo", query: "at=step-waiting" })} prefetch={false}
                      aria-label="what the inputs still wait on before Review & sign opens, on To do">what they still wait on</Link>)</span>
              </Fragment>
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
