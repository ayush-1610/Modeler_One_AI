import Link from "next/link";

import { InputsWorkspace, type Tab } from "@/components/inputs/InputsWorkspace";
import { Stepper } from "@/components/kit/Stepper";
import { getSteps, STEP_ROUTES } from "@/lib/pipeline";

/** Step 2 · Inputs (redesign §3.2), in place of P2–P4's per-item acceptance: one workspace, five tabs, what is still
 *  missing to run beside them. `?tab=studies` opens a tab (the project page's "Add data"). */
export default async function InputsPage({ params, searchParams }: {
  params: Promise<{ projectId: string }>; searchParams: Promise<{ tab?: string }>;
}) {
  const { projectId } = await params;
  const { tab } = await searchParams;
  const start = (await getSteps(projectId)).data?.find((s) => s.step === "start");
  return (
    <main>
      <Stepper projectId={projectId} current="inputs" />
      {start && start.state !== "done" && (
        // page review 1: Inputs comes after Start; reached by its address, it says so in red
        <div className="banner err" role="alert" data-testid="inputs-start-not-done">
          <span aria-hidden>⚠ </span>Start is not finished ({start.reasons.length} left): {start.reasons.join(" · ")}.{" "}
          <Link href={STEP_ROUTES.start(projectId)}>Finish Start first</Link>.
        </div>
      )}
      <InputsWorkspace projectId={projectId} initialTab={tab as Tab | undefined} />
    </main>
  );
}
