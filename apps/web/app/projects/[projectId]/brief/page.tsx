import { BriefReview } from "@/components/brief/BriefReview";
import { PhaseRail } from "@/components/PhaseRail";

/** P1 · Brief & data plan — review layer L1. */
export default async function BriefPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <h1>Brief &amp; data plan</h1>
      <PhaseRail projectId={projectId} current="P1" />
      <p className="muted" style={{ maxWidth: "var(--measure)" }}>
        <strong>Review layer 1.</strong> Only what matters for the PBPK / popPK model, in the same structure for every
        project. Click a source chip to see the exact words on the page. Any change says why; approval is possible once
        nothing required is missing and every question is answered or accepted.
      </p>
      <BriefReview projectId={projectId} />
    </main>
  );
}
