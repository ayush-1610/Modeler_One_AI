import { Stepper } from "@/components/kit/Stepper";
import { StartScreen } from "@/components/start/StartScreen";

/** Step 1 · Start (redesign §3.1): the drug and its files, the short brief and the data checklist. Replaces P0 and P1. */
export default async function StartStepPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <Stepper projectId={projectId} current="start" waiting={false} />
      <StartScreen projectId={projectId} />
    </main>
  );
}
