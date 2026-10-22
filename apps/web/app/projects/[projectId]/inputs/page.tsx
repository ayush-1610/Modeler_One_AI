import { InputsWorkspace, type Tab } from "@/components/inputs/InputsWorkspace";
import { Stepper } from "@/components/kit/Stepper";

/** Step 2 · Inputs (redesign §3.2), in place of P2–P4's per-item acceptance: one workspace, five tabs, what is still
 *  missing to run beside them. `?tab=studies` opens a tab (the project page's "Add data"). */
export default async function InputsPage({ params, searchParams }: {
  params: Promise<{ projectId: string }>; searchParams: Promise<{ tab?: string }>;
}) {
  const { projectId } = await params;
  const { tab } = await searchParams;
  return (
    <main>
      <Stepper projectId={projectId} current="inputs" />
      <InputsWorkspace projectId={projectId} initialTab={tab as Tab | undefined} />
    </main>
  );
}
