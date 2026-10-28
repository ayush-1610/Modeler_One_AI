import Link from "next/link";

import { getSteps, STEP_ROUTES, type StepId, type StepState } from "@/lib/pipeline";

const STATE_LABEL: Record<StepState, string> = {
  done: "done",
  needs_you: "needs you",
  running: "running",
  not_started: "not started",
};

/** The project's four steps (redesign §3): Start, Inputs, Review & sign, Run, each with where it stands. The step the
 *  page belongs to is marked, and what it waits on is written out under the row. Until Start is done the steps after it
 *  cannot be opened from here (page review 1); the project's history is on the Projects page. */
export async function Stepper({ projectId, current, waiting = true }: {
  projectId: string; current?: StepId;
  /** Write out what the current step waits on (off where the page lists it itself, as Start does). */
  waiting?: boolean;
}) {
  const live = await getSteps(projectId);
  if (!live.data) return null; // the stepper is navigation; the page itself reports a read problem
  const here = live.data.find((s) => s.step === current);
  const start = live.data.find((s) => s.step === "start");
  const locked = start !== undefined && start.state !== "done";
  return (
    <div className="stepper-wrap">
      <nav className="stepper" aria-label="Project steps" data-testid="stepper">
        <ol>
          {live.data.map((s, i) => (
            <li key={s.step} className={`step ${s.state}${current === s.step ? " current" : ""}`}
                data-testid={`step-${s.step}`} data-state={s.state}>
              {locked && s.step !== "start" && current !== s.step ? (
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
                      title={s.reasons.length ? s.reasons.join("\n") : `${s.label}: ${STATE_LABEL[s.state]}`}>
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
          <strong>Waiting on you:</strong> {here.reasons.join(" · ")}
        </p>
      )}
    </div>
  );
}
