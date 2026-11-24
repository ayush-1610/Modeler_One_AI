import Link from "next/link";
import { Suspense } from "react";

import { getSteps, type StepId } from "@/lib/pipeline";
import { inputsHref, stepReason, stepWhere } from "@/lib/words";

/** What the page's step waits on, in plain words, under the page's header (redesign §3; console redesign slice 1). The
 *  four steps themselves moved into the side navigation (components/shell/SideNav.tsx, the approved design: no step bar
 *  under the header); this keeps the line that says what to do next and where, each part linking to the area of Inputs
 *  where it is settled (a model check's raw name, "S0 completeness (MS-01 §2.2)", reads "compound values missing":
 *  lib/words.ts). It streams in after the page's head, sharing the page's read of /steps (`preloadSteps`, cache()d per
 *  request). Its links are not prefetched (final review round 4). Named `Stepper` until slice 9, when it was the step bar. */
export function StepWaiting(props: StepWaitingProps) {
  return (
    <Suspense fallback={null}>
      <StepWaitingBody {...props} />
    </Suspense>
  );
}

/** Start reading the project's steps now, alongside the page's other reads; StepWaiting then uses the same answer. */
export function preloadSteps(projectId: string) {
  void getSteps(projectId);
}

type StepWaitingProps = { projectId: string; current?: StepId };

async function StepWaitingBody({ projectId, current }: StepWaitingProps) {
  const live = await getSteps(projectId);
  if (!live.data) return null; // navigation help only; the page itself reports a read problem
  const here = live.data.find((s) => s.step === current);
  return (
    <>
      {here && here.state === "needs_you" && here.reasons.length > 0 && (
        <p className="step-waiting banner warn" data-testid="step-waiting">
          <strong>Waiting on you:</strong>{" "}
          {here.reasons.map((r, i) => {
            // a model check opens the area of Inputs where it is settled, and its other ways where it has them (OWN-13, gap
            // 11): a tablet study's formulation names the lever that fits what the project holds (round 4: the API's
            // `formulation`, lib/words.ts `formulationWays`), "ask the client" opening its line of To do
            const at = stepWhere(r, here.formulation);
            return (
              <span key={r}>{i > 0 && " · "}
                {at ? <Link prefetch={false} href={inputsHref(projectId, at)} title={at.fix} data-testid={`step-waiting-go-${at.area}`}>{at.waiting}</Link> : stepReason(r)}
                {at && at.ways.length > 0 && <> ({at.ways.map((w, j) => (
                  <span key={w.id}>{j > 0 && ", or "}<Link prefetch={false} href={inputsHref(projectId, w)} data-testid={`step-waiting-${w.id === "ask" ? "or-todo" : w.id}`}>{w.say}</Link>
                    {w.area !== "todo" && <> on {w.name}</>}</span>
                ))})</>}
              </span>
            );
          })}
        </p>
      )}
    </>
  );
}
