import { Stepper } from "@/components/kit/Stepper";
import { PlanCanvas } from "@/components/plan/PlanCanvas";

/** Step 3 · Review & sign (redesign §3.3): the studies and roles on the MS-01 canvas, the review table, credibility,
 *  the live validator and the signature. */
export default async function PlanPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main className="wide">
      <Stepper projectId={projectId} current="review" />
      <PlanCanvas projectId={projectId} />
    </main>
  );
}
