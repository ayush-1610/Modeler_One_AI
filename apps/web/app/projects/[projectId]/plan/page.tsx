import { PhaseRail } from "@/components/PhaseRail";
import { PlanCanvas } from "@/components/plan/PlanCanvas";

/** P5 · Model plan — review layer L3. */
export default async function PlanPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main className="wide">
      <h1>Model plan</h1>
      <PhaseRail projectId={projectId} current="P5" />
      <p className="muted" style={{ maxWidth: "var(--measure)" }}>
        <strong>Review layer 3.</strong> The plan starts as the MS-01 default, computed exactly as the MAP is generated. Move a
        dataset by dragging it onto a stage of the development and validation graph; each move needs a reason and is kept
        when the default or the planning agent runs again. The validator checks every MS-01 rule as you go; the MAP is
        generated from the plan and signed only when nothing is left open.
      </p>
      <PlanCanvas projectId={projectId} />
    </main>
  );
}
