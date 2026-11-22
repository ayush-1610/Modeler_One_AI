import { Suspense } from "react";

import { Report } from "@/components/dataroom/Report";
import { getProject } from "@/lib/reads";

/** The Data room's evidence report, ready to print (plan 2026-11-21 v2 §5 step 8): the Data room's "Export report" opens
 *  it with `?print=1`, and the browser's print dialog saves it as a PDF. */
export default async function DataRoomReportPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const project = (await getProject(projectId)).data;
  return (
    <main className="dr-report-main">
      <Suspense fallback={<p className="muted">Laying out the report…</p>}>
        <Report projectId={projectId} project={project?.name || projectId} />
      </Suspense>
    </main>
  );
}
