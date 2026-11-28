import Link from "next/link";

import { InputsWorkspace } from "@/components/inputs/InputsWorkspace";
import { StepWaiting } from "@/components/kit/StepWaiting";
import { getSteps, STEP_ROUTES } from "@/lib/pipeline";
import { Icon } from "@/components/kit/icons";

/** Step 2 · Inputs (redesign §3.2), in place of P2–P4's per-item acceptance: one workspace, its areas in a bar that stays
 *  in view (To do, the five data areas, Client files: plan 2026-11-14 slice 1). `?tab=studies` opens an area (the project
 *  page's "Add data"); `todo` and `files` too; `only=1` shows only what needs the person and `status=` narrows To do to a
 *  status word (slice 2: the page writes all three as they change). The step bar scrolls away with the page here.
 *
 *  Start's lock is on sending to the model, not on Inputs (the owner's D4, 2026-11-27; plan 2026-11-27-one-way-in step
 *  5, replacing decision 7 of 2026-10-29): Inputs opens while Start waits on the person, with a banner that says what
 *  Start still needs and that nothing is sent to the model until it is finished. */
export default async function InputsPage({ params, searchParams }: {
  params: Promise<{ projectId: string }>; searchParams: Promise<{ tab?: string; only?: string; status?: string }>;
}) {
  const { projectId } = await params;
  const { tab, only, status } = await searchParams;
  const steps = (await getSteps(projectId)).data;
  const start = steps?.find((s) => s.step === "start");
  const waiting = start !== undefined && start.state !== "done";
  return (
    <main>
      <InputsWorkspace projectId={projectId} initialTab={tab} initialOnly={only === "1"} initialStatus={status}
                       steps={(
                         <>
                           <StepWaiting projectId={projectId} current="inputs" />
                          {waiting && (
                            // the data can be gathered and confirmed now; it is sent to the model once Start is finished (D4)
                            <div className="banner warn" role="status" data-testid="inputs-start-not-done">
                              <Icon name="alert" /> Start is not finished ({start.reasons.length} left): {start.reasons.join(" · ")}.
                              {" "}Nothing is sent to the model until it is.{" "}
                              <Link href={STEP_ROUTES.start(projectId)} prefetch={false} data-testid="inputs-finish-start">Finish Start</Link>.
                            </div>
                          )}
                         </>
                       )} />
    </main>
  );
}
