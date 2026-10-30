import Link from "next/link";

import { InputsWorkspace, type Tab } from "@/components/inputs/InputsWorkspace";
import { Stepper } from "@/components/kit/Stepper";
import { getSteps, STEP_ROUTES } from "@/lib/pipeline";

/** Step 2 · Inputs (redesign §3.2), in place of P2–P4's per-item acceptance: one workspace, five tabs, what is still
 *  missing to run beside them. `?tab=studies` opens a tab (the project page's "Add data").
 *
 *  Inputs comes after Start (page review 1, the owner's decision 7 of 2026-10-29). While Start waits on the person,
 *  Inputs is blocked: it says what Start still needs and links to it. Inputs that have begun stay open with a red
 *  banner, so a project whose Start gains a requirement later is never locked out (the step bar's rule, #105). A
 *  project made through the API with no proposal has no Start to finish: it keeps the banner, never the block. */
export default async function InputsPage({ params, searchParams }: {
  params: Promise<{ projectId: string }>; searchParams: Promise<{ tab?: string }>;
}) {
  const { projectId } = await params;
  const { tab } = await searchParams;
  const steps = (await getSteps(projectId)).data;
  const start = steps?.find((s) => s.step === "start");
  const inputs = steps?.find((s) => s.step === "inputs");
  const waiting = start !== undefined && start.state !== "done";
  if (start?.state === "needs_you" && inputs?.state === "not_started") {
    return (
      <main>
        <Stepper projectId={projectId} current="inputs" />
        <section className="card inputs-blocked" data-testid="inputs-blocked">
          <h1>Inputs come after Start</h1>
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
      <Stepper projectId={projectId} current="inputs" />
      {waiting && (
        // inputs that have begun stay open; Start still says what it needs, in red
        <div className="banner err" role="alert" data-testid="inputs-start-not-done">
          <span aria-hidden>⚠ </span>Start is not finished ({start.reasons.length} left): {start.reasons.join(" · ")}.{" "}
          <Link href={STEP_ROUTES.start(projectId)}>Finish Start first</Link>.
        </div>
      )}
      <InputsWorkspace projectId={projectId} initialTab={tab as Tab | undefined} />
    </main>
  );
}
