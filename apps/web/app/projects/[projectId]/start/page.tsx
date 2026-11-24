import { StartScreen } from "@/components/start/StartScreen";

/** Step 1 · Start (redesign §3.1), replacing P0 review and P1: one screen, no approvals. Start lists what it waits on
 *  itself, so it draws no "Waiting on you" line. */
export default async function StartPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <StartScreen projectId={projectId} />
    </main>
  );
}
