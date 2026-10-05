import { EvidenceReview } from "@/components/evidence/EvidenceReview";
import { PhaseRail } from "@/components/PhaseRail";

/** P2 · Literature and public data — review layer L2a. */
export default async function EvidencePage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <h1>Literature &amp; public data</h1>
      <PhaseRail projectId={projectId} current="P2" />
      <p className="muted" style={{ maxWidth: "var(--measure)" }}>
        <strong>Review layer 2a.</strong> For every input the data plan expects from the literature: the values found,
        side by side, each with its source, the exact quote, the conditions, the value converted to the PK-Sim unit and a
        confidence grade. Conflicting values are shown, never averaged. Accept or reject each with a reason; the phase
        closes when every required item has an accepted value or is recorded as not available.
      </p>
      <EvidenceReview projectId={projectId} />
    </main>
  );
}
