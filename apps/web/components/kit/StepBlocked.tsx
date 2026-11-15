"use client";

// A step that cannot open yet says why and where to go (the 2026-11-11 audit, item 2). It reads the project's steps and
// lists what the earlier step still waits on, each in words, with one way forward, instead of an error on an empty page.
// What Inputs waits on are the model's checks: each is said in the step bar's words (lib/words.ts), with what to do and a
// link to the area of Inputs where it is done, and how they stand to the count of Inputs' To do (final review OWN-13).
// What the API said is never printed as it came ("S0 completeness (MS-01 §2.2); …": round 3, OWN-8): the list above says
// each check; only with no such list is it said, in the same words (lib/words.ts `readinessText`).

import Link from "next/link";
import type { ReactNode } from "react";

import { useResource } from "@/lib/hooks";
import { STEP_ROUTES, type StepId } from "@/lib/pipeline";
import { plain } from "@/lib/plain";
import { inputsHref, readinessText, stepReason, stepWhere } from "@/lib/words";

const ORDER: StepId[] = ["start", "inputs", "review", "run"];
const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function StepBlocked({ projectId, step, title, detail, fallback, testId }: {
  projectId: string;
  /** The step this page belongs to; the first earlier step that is not done is the one to finish. */
  step: StepId;
  title: string;
  /** What the API said: shown small, in words, only when no list of what the earlier step waits on says it already. */
  detail?: string | null;
  /** What is said when every earlier step is done but this one still cannot start (what it lacks, in words). */
  fallback?: ReactNode;
  testId?: string;
}) {
  const steps = useResource("/api/v1/projects/{project_id}/steps", { project_id: projectId }, { select: (d) => d.steps.map((s) => ({ ...s, reasons: s.reasons.map(plain) })) });
  const before = (steps.data ?? []).filter((s) => ORDER.indexOf(s.step) < ORDER.indexOf(step));
  const waiting = before.find((s) => s.state !== "done") ?? null;
  return (
    <section className="card step-blocked" data-testid={testId ?? "step-blocked"}>
      <h2>{title}</h2>
      {waiting ? (
        <>
          <p className="muted">{waiting.label} is not finished.{" "}
            {waiting.reasons.length ? `${waiting.reasons.length} ${waiting.reasons.length === 1 ? "thing still needs" : "things still need"} you there:`
              : "It has not been worked on yet."}</p>
          {waiting.reasons.length > 0 && (
            <ul data-testid="step-blocked-reasons">
              {waiting.reasons.map((r) => {
                const at = waiting.step === "inputs" ? stepWhere(r) : null;
                return (
                  <li key={r} data-testid={at ? `step-blocked-check-${at.area}` : undefined}>
                    {at ? <><Link href={inputsHref(projectId, at)}>{capital(stepReason(r))}</Link>: {at.fix}
                      {/* its other ways, as the step bar says them: "(add a product on Products and dissolution, or ask the
                          client on To do)", each opening its form or its line (round 3, gap 11) */}
                      {(at.add || at.or) && <> (
                        {at.add && <><Link href={inputsHref(projectId, at.add)} data-testid="step-blocked-add">{at.add.say}</Link> on {at.add.name}</>}
                        {at.add && at.or && ", or "}
                        {at.or && <><Link href={inputsHref(projectId, at.or)} data-testid="step-blocked-or">{at.or.say}</Link> on {at.or.name}</>})</>}</>
                      : capital(stepReason(r))}
                  </li>
                );
              })}
            </ul>
          )}
          {waiting.step === "inputs" && waiting.reasons.some((r) => stepWhere(r)) && (
            <p className="muted fs-13" data-testid="step-blocked-todo">These are the model&apos;s checks. Inputs&apos; To do lists the items
              behind them one by one (one check can stand for several items), and the client&apos;s data still to confirm, so its count is
              of items, not of checks.</p>
          )}
          <Link className="btn primary" href={STEP_ROUTES[waiting.step](projectId)} data-testid="step-blocked-go">
            Go to {waiting.label}
          </Link>
        </>
      ) : steps.data ? (
        fallback ?? <p className="muted">The earlier steps are done; this step is being prepared.</p>
      ) : (
        <p className="muted">Reading where the project stands…</p>
      )}
      {detail && (steps.data || steps.problem) && !waiting?.reasons.length && <p className="step-blocked-detail" data-testid="step-blocked-detail">{readinessText(plain(detail))}</p>}
    </section>
  );
}
