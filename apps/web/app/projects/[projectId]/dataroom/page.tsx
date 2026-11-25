import Link from "next/link";
import { Suspense } from "react";

import { DataRoom } from "@/components/dataroom/DataRoom";
import { Hero } from "@/components/kit";
import { StepWaiting } from "@/components/kit/StepWaiting";

/** Step 2 · Inputs, the Data room (plan 2026-11-21 v2 §5, §10): the client's delivery read, checked and laid out as the
 *  evidence report and the PK-Sim inputs, each value with its source. The earlier Inputs page stays reachable (§4: the
 *  two live side by side until the owner retires the old reading paths). "Export report" opens the printable report. */
export default async function DataRoomPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const report = `/projects/${encodeURIComponent(projectId)}/dataroom/report?print=1`;
  return (
    <main>
      <Hero tone="inputs" size="slim" eyebrow="Step 2 of 4 · Inputs" title="Data room"
            lede="The client's delivery, read and checked: every value with the file, page and line it came from."
            actions={<Link className="btn" href={report} target="_blank" rel="noopener" prefetch={false} data-testid="export-report">Export report</Link>} />
      <StepWaiting projectId={projectId} current="inputs" />
      <Suspense fallback={<p className="muted">Opening the Data room…</p>}>
        <DataRoom projectId={projectId} />
      </Suspense>
    </main>
  );
}
