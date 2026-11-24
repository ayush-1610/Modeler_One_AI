import Link from "next/link";

import { DataPlan } from "@/components/dataplan/DataPlan";
import { Hero } from "@/components/kit";
import { serverGet } from "@/lib/api";

// The Data plan (P-13b, the console redesign's slice 4a): read-mostly; edits stay on the cards in Inputs.
export default async function DataPlanPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const live = await serverGet("/api/v1/projects/{project_id}/requirements", { project_id: projectId });
  return (
    <main>
      <Hero title="Data plan" lede="Which data the project's applications require, who provides each item, and whether it is covered." />
      {live.data ? <DataPlan projectId={projectId} page={live.data} /> : (
        <div className="banner info" data-testid="data-plan-none">
          No data plan yet: it is derived from the brief once Start is confirmed. <Link href={`/projects/${encodeURIComponent(projectId)}/start`}>Go to Start</Link>.
        </div>
      )}
    </main>
  );
}
