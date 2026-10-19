import { Stepper } from "@/components/kit/Stepper";
import { StartScreen } from "@/components/start/StartScreen";

/** Step 1 · Start (redesign §3.1), replacing P0 review and P1: one screen, no approvals. The old brief page stays
 *  until R5 removes it. */
export default async function StartPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <Stepper projectId={projectId} current="start" waiting={false} />
      <StartScreen projectId={projectId} />
    </main>
  );
}
