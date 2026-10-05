import Link from "next/link";

import { EvidenceReview } from "@/components/evidence/EvidenceReview";
import { ObservedData } from "@/components/evidence/ObservedData";
import { PhaseRail } from "@/components/PhaseRail";

/** P2 · Literature and public data — review layer L2a. */
export default async function EvidencePage({
  params, searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { projectId } = await params;
  const { tab = "parameters" } = await searchParams;
  return (
    <main>
      <h1>Literature &amp; public data</h1>
      <PhaseRail projectId={projectId} current="P2" />
      <p className="muted" style={{ maxWidth: "var(--measure)" }}>
        <strong>Review layer 2a.</strong> For every input the data plan expects from the literature: the values found,
        side by side, each with its source, the exact quote, the conditions, the value converted to the PK-Sim unit and a
        confidence grade; and the observed clinical data, each with its origin. Conflicting values are shown, never
        averaged. Accept or reject each with a reason; the phase closes when every required item has an accepted value or
        dataset, or is recorded as not available.
      </p>
      <nav className="tabs" aria-label="Review layer 2a">
        <Link href={`/projects/${projectId}/evidence?tab=parameters`} className={tab === "parameters" ? "active" : ""}>Parameters</Link>
        <Link href={`/projects/${projectId}/evidence?tab=observed`} className={tab === "observed" ? "active" : ""}
              data-testid="tab-observed">Observed data</Link>
      </nav>
      {tab === "observed" ? <ObservedData projectId={projectId} /> : <EvidenceReview projectId={projectId} />}
    </main>
  );
}
