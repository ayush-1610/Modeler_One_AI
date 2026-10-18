import Link from "next/link";

import { getSteps, INPUTS_PAGES, STEP_ROUTES, type StepId, type StepState } from "@/lib/pipeline";

const STATE_LABEL: Record<StepState, string> = {
  done: "done",
  needs_you: "needs you",
  running: "running",
  not_started: "not started",
};

/** The project's four steps (redesign §3): Start, Inputs, Review & sign, Run, each with where it stands. The step the
 *  page belongs to is marked, and what it waits on is written out under the row, unless the page lists it itself
 *  (`waiting={false}`). Inputs still spans three pages until they become one workspace (R3), so its pages are linked
 *  while you are in it. */
export async function Stepper({ projectId, current, page, waiting = true }: {
  projectId: string; current?: StepId; page?: string; waiting?: boolean;
}) {
  const live = await getSteps(projectId);
  if (!live.data) return null; // the stepper is navigation; the page itself reports a read problem
  const here = live.data.find((s) => s.step === current);
  return (
    <div className="stepper-wrap">
      <nav className="stepper" aria-label="Project steps" data-testid="stepper">
        <ol>
          {live.data.map((s, i) => (
            <li key={s.step} className={`step ${s.state}${current === s.step ? " current" : ""}`}
                data-testid={`step-${s.step}`} data-state={s.state}>
              <Link href={STEP_ROUTES[s.step](projectId)} aria-current={current === s.step ? "step" : undefined}
                    title={s.reasons.length ? s.reasons.join("\n") : `${s.label}: ${STATE_LABEL[s.state]}`}>
                <span className="step-n" aria-hidden>{s.state === "done" ? "✓" : i + 1}</span>
                <span className="step-text">
                  <span className="step-label">{s.label}</span>
                  <span className="step-state">{STATE_LABEL[s.state]}</span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
        <Link href={`/projects/${projectId}/history`} className="step-history">History</Link>
      </nav>
      {current === "inputs" && (
        <nav className="step-pages" aria-label="Inputs pages">
          {INPUTS_PAGES.map((p) => (
            <Link key={p.id} href={p.href(projectId)} className={page === p.id ? "active" : ""}
                  aria-current={page === p.id ? "page" : undefined}>{p.label}</Link>
          ))}
        </nav>
      )}
      {waiting && here && here.state === "needs_you" && here.reasons.length > 0 && (
        <p className="step-waiting" data-testid="step-waiting">
          <strong>Waiting on you:</strong> {here.reasons.join(" · ")}
        </p>
      )}
    </div>
  );
}
