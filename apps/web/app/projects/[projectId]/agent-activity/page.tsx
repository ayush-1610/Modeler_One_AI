import Link from "next/link";

import { ApiProblem, Hero } from "@/components/kit";
import { AgentRunsTable } from "@/components/records/AgentRuns";
import { getAgentRuns } from "@/lib/reads";

// Agent activity (P-19, the console redesign's slice 7): what each AI agent did on this project, for the modeller's
// trust and the report's "how it was made". Read from `GET /projects/{id}/agent-runs` (R-N05), fifty at a time, newest
// first; each run opens on its steps. No cost here: it stays in the admin console.

export default async function AgentActivityPage({ params, searchParams }: {
  params: Promise<{ projectId: string }>; searchParams: Promise<{ before?: string }>;
}) {
  const { projectId } = await params;
  const { before } = await searchParams;
  const live = await getAgentRuns(projectId, before);
  const base = `/projects/${encodeURIComponent(projectId)}/agent-activity`;
  return (
    <main>
      <Hero tone="history" eyebrow="Project record" title="Agent activity" testId="agent-activity-head"
            lede="Each AI agent run on this project: which agent, on which model, who started it, how long it took, what it used,
              and what the runtime refused. An agent proposes; a person or code's checks decide." />
      {live.problem ? <ApiProblem problem={live.problem} /> : (
        <>
          <AgentRunsTable runs={live.data?.runs ?? []} base={base} />
          <p className="muted fs-13 m-12-0-0">
            {before && <Link href={base} prefetch={false} data-testid="agent-runs-newest">Newest runs</Link>}
            {before && live.data?.next_before && " · "}
            {live.data?.next_before && (
              <Link href={`${base}?before=${encodeURIComponent(live.data.next_before)}`} prefetch={false} data-testid="agent-runs-older">
                Older runs</Link>
            )}
          </p>
        </>
      )}
    </main>
  );
}
