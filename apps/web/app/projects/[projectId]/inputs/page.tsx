import { InputsWorkspace } from "@/components/inputs/InputsWorkspace";
import { Stepper } from "@/components/kit/Stepper";

/** Step 2 · Inputs (redesign §3.2), replacing P2–P4's per-item acceptance: one workspace, five tabs, what is still
 *  missing to run beside them. The Literature and Client data pages stay reachable until R5 retires them. */
export default async function InputsPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <Stepper projectId={projectId} current="inputs" page="inputs" />
      <InputsWorkspace projectId={projectId} />
    </main>
  );
}
