import Link from "next/link";

import { InputsWorkspace } from "@/components/inputs/InputsWorkspace";
import { Hero } from "@/components/kit";
import { Stepper } from "@/components/kit/Stepper";
import { getSteps, STEP_ROUTES } from "@/lib/pipeline";

/** Step 2 · Inputs (redesign §3.2), in place of P2–P4's per-item acceptance: one workspace, its areas in a bar that stays
 *  in view (To do, the five data areas, Client files: plan 2026-11-14 slice 1). `?tab=studies` opens an area (the project
 *  page's "Add data"); `todo` and `files` too; `only=1` shows only what needs the person and `status=` narrows To do to a
 *  status word (slice 2: the page writes all three as they change). The step bar scrolls away with the page here.
 *
 *  Inputs comes after Start (page review 1, the owner's decision 7 of 2026-10-29). While Start waits on the person,
 *  Inputs is blocked: it says what Start still needs and links to it. Inputs that have begun stay open with a red
 *  banner, so a project whose Start gains a requirement later is never locked out (the step bar's rule, #105). A
 *  project made through the API with no proposal has no Start to finish: it keeps the banner, never the block. */
export default async function InputsPage({ params, searchParams }: {
  params: Promise<{ projectId: string }>; searchParams: Promise<{ tab?: string; only?: string; status?: string }>;
}) {
  const { projectId } = await params;
  const { tab, only, status } = await searchParams;
  const steps = (await getSteps(projectId)).data;
  const start = steps?.find((s) => s.step === "start");
  const inputs = steps?.find((s) => s.step === "inputs");
  const waiting = start !== undefined && start.state !== "done";
  if (start?.state === "needs_you" && inputs?.state === "not_started") {
    return (
      <main>
        <Hero tone="inputs" eyebrow="Step 2 of 4" title="Inputs" lede="The inputs are gathered once Start is finished." />
        <Stepper projectId={projectId} current="inputs" sticky={false} />
        <section className="card inputs-blocked" data-testid="inputs-blocked">
          <h2>Inputs come after Start</h2>
          <p>Start is not finished. The inputs are gathered once it is: {start.reasons.length}{" "}
            {start.reasons.length === 1 ? "thing still needs" : "things still need"} you.</p>
          <ul>{start.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          <Link className="btn primary" href={STEP_ROUTES.start(projectId)} data-testid="inputs-blocked-start">Finish Start</Link>
        </section>
      </main>
    );
  }
  return (
    <main>
      <InputsWorkspace projectId={projectId} initialTab={tab} initialOnly={only === "1"} initialStatus={status}
                       steps={(
                         <>
                           <Stepper projectId={projectId} current="inputs" sticky={false} />
                          {waiting && (
                            // inputs that have begun stay open; Start still says what it needs, in red
                            <div className="banner err" role="alert" data-testid="inputs-start-not-done">
                              <span aria-hidden>⚠ </span>Start is not finished ({start.reasons.length} left): {start.reasons.join(" · ")}.{" "}
                              <Link href={STEP_ROUTES.start(projectId)}>Finish Start first</Link>.
                            </div>
                          )}
                         </>
                       )} />
    </main>
  );
}
