import Link from "next/link";
import { Suspense } from "react";

import { StepperSkeleton } from "@/components/kit/Skeleton";

import { getSteps, STEP_ROUTES, type StepId, type StepState } from "@/lib/pipeline";
import { stepReason, stepWhere } from "@/lib/words";

const STATE_LABEL: Record<StepState, string> = {
  done: "done",
  needs_you: "needs you",
  running: "running",
  not_started: "not started",
};

/** The project's four steps (redesign §3): Start, Inputs, Review & sign, Run, each with where it stands. The step the
 *  page belongs to is marked, and what it waits on is written out under the row, in plain words (a model check's raw
 *  name, "S0 completeness (MS-01 §2.2)", reads "compound values missing": lib/words.ts). Until Start is done the steps after it
 *  that have not begun cannot be opened from here (page review 1); a step that has begun stays open, so a project whose
 *  Start gains a requirement later is never locked out of its plan or its campaign. The project's history is on the
 *  Projects page.
 *
 *  The steps stream in (audit item 9): the page's head paints at once and the bar's place is held by a skeleton of its
 *  size until /steps answers. A page starts that read with its own (`preloadSteps`), so the two run side by side and the
 *  bar shares the page's answer (lib/pipeline.ts getSteps is cache()d for the request). */
export function Stepper(props: StepperProps) {
  return (
    <Suspense fallback={<StepperSkeleton />}>
      <StepperBody {...props} />
    </Suspense>
  );
}

/** Start reading the project's steps now, alongside the page's other reads; the Stepper then uses the same answer. */
export function preloadSteps(projectId: string) {
  void getSteps(projectId);
}

type StepperProps = {
  projectId: string; current?: StepId;
  /** Write out what the current step waits on (off where the page lists it itself, as Start does). */
  waiting?: boolean;
  /** Kept in view as the page scrolls (off on Inputs, whose area bar is what stays in view: plan 2026-11-14 slice 1). */
  sticky?: boolean;
};

async function StepperBody({ projectId, current, waiting = true, sticky = true }: StepperProps) {
  const live = await getSteps(projectId);
  if (!live.data) return null; // the stepper is navigation; the page itself reports a read problem
  const here = live.data.find((s) => s.step === current);
  const start = live.data.find((s) => s.step === "start");
  const locked = start !== undefined && start.state !== "done";
  return (
    <div className={sticky ? "stepper-wrap" : "stepper-wrap static"}>
      <nav className="stepper" aria-label="Project steps" data-testid="stepper">
        <ol>
          {live.data.map((s, i) => (
            <li key={s.step} className={`step ${s.state}${current === s.step ? " current" : ""}`}
                data-testid={`step-${s.step}`} data-state={s.state}>
              {locked && s.step !== "start" && s.state === "not_started" && current !== s.step ? (
                <span className="step-locked" aria-disabled="true" data-testid={`step-${s.step}-locked`}
                      title={`Finish Start first: ${start.reasons.join("; ")}`}>
                  <span className="step-n" aria-hidden>{i + 1}</span>
                  <span className="step-text">
                    <span className="step-label">{s.label}</span>
                    <span className="step-state">after Start</span>
                  </span>
                </span>
              ) : (
                <Link href={STEP_ROUTES[s.step](projectId)} aria-current={current === s.step ? "step" : undefined}
                      title={s.reasons.length ? s.reasons.map(stepReason).join("\n") : `${s.label}: ${STATE_LABEL[s.state]}`}>
                  <span className="step-n" aria-hidden>{s.state === "done" ? "✓" : i + 1}</span>
                  <span className="step-text">
                    <span className="step-label">{s.label}</span>
                    <span className="step-state">{STATE_LABEL[s.state]}</span>
                  </span>
                </Link>
              )}
            </li>
          ))}
        </ol>
      </nav>
      {waiting && here && here.state === "needs_you" && here.reasons.length > 0 && (
        <p className="step-waiting" data-testid="step-waiting">
          <strong>Waiting on you:</strong>{" "}
          {here.reasons.map((r, i) => {
            // a model check opens the area of Inputs where it is settled, and its second way where it has one (OWN-13, gap 11)
            const at = stepWhere(r);
            const href = (area: string) => `/projects/${encodeURIComponent(projectId)}/inputs?tab=${area}`;
            return (
              <span key={r}>{i > 0 && " · "}
                {at ? <Link href={href(at.area)} title={at.fix} data-testid={`step-waiting-go-${at.area}`}>{stepReason(r)}</Link> : stepReason(r)}
                {at?.or && <> (on {at.name}, or <Link href={href(at.or.area)} data-testid={`step-waiting-or-${at.or.area}`}>{at.or.say}</Link>)</>}
              </span>
            );
          })}
        </p>
      )}
    </div>
  );
}
