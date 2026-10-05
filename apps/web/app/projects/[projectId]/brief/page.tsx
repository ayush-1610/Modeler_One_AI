import Link from "next/link";

import { BriefReview } from "@/components/brief/BriefReview";
import { DataPlan } from "@/components/brief/DataPlan";
import { PhaseRail } from "@/components/PhaseRail";

const TABS = [
  { id: "brief", label: "Brief" },
  { id: "data-plan", label: "Data plan" },
  { id: "feasibility", label: "Feasibility" },
] as const;

/** P1 · Brief & data plan — review layer L1. */
export default async function BriefPage({
  params, searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { projectId } = await params;
  const { tab = "brief" } = await searchParams;
  return (
    <main>
      <h1>Brief &amp; data plan</h1>
      <PhaseRail projectId={projectId} current="P1" />
      <p className="muted" style={{ maxWidth: "var(--measure)" }}>
        <strong>Review layer 1.</strong> Only what matters for the PBPK / popPK model, in the same structure for every
        project. Click a source chip to see the exact words on the page. Any change says why; approval is possible once
        nothing required is missing and every question is answered or accepted. The data plan follows from the approved
        brief: every PK-Sim input and observed dataset, who provides it, and for what.
      </p>
      <nav className="tabs" aria-label="Review layer 1">
        {TABS.map((t) => (
          <Link key={t.id} href={`/projects/${projectId}/brief?tab=${t.id}`} className={tab === t.id ? "active" : ""}
                data-testid={`tab-${t.id}`}>{t.label}</Link>
        ))}
      </nav>
      {tab === "brief" && <BriefReview projectId={projectId} />}
      {tab === "data-plan" && <DataPlan projectId={projectId} view="plan" />}
      {tab === "feasibility" && <DataPlan projectId={projectId} view="feasibility" />}
    </main>
  );
}
