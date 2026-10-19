import Link from "next/link";

import { BriefReview } from "@/components/brief/BriefReview";
import { Stepper } from "@/components/kit/Stepper";

/** The full brief, every field of it: Start (redesign §3.1) shows the short brief, and the products, populations and the
 *  proposal's own data-plan statements are edited here until Inputs and Review & sign take them over (R3, R4). Nothing
 *  is approved (D-27); the data checklist and its feasibility warnings are on Start. */
export default async function BriefPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <h1>The full brief</h1>
      <Stepper projectId={projectId} current="start" />
      <p className="muted" style={{ maxWidth: "var(--measure)" }}>
        Every field the proposal can fill, in the same structure for every project. Click a source chip to see the exact
        words on the page. Nothing here is approved: <Link href={`/projects/${projectId}/start`}>Start</Link> shows what the
        model needs and the data checklist, and you review everything once, when you sign the plan.
      </p>
      <BriefReview projectId={projectId} />
    </main>
  );
}
