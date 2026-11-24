import { ApiProblem, Hero } from "@/components/kit";
import { RunSteps } from "@/components/records/AgentRuns";
import { getAgentRun } from "@/lib/reads";
import { duration } from "@/lib/runs";

// One agent run (P-19b, the console redesign's slice 7): what it was asked to do on which model, what it used, and
// each of its steps (every answer of the model, each tool call and result, each refusal and model switch), read from
// `GET /projects/{id}/agent-runs/{run}`. Read only.

export default async function AgentRunPage({ params }: { params: Promise<{ projectId: string; runId: string }> }) {
  const { projectId, runId } = await params;
  const live = await getAgentRun(projectId, runId);
  const run = (live.data?.run ?? null) as Record<string, unknown> | null;
  const steps = (live.data?.steps ?? []) as Parameters<typeof RunSteps>[0]["steps"];
  if (!run) {
    return (
      <main>
        <Hero tone="history" eyebrow="Agent run" title={<code>{runId}</code>} />
        <ApiProblem problem={live.problem ?? "The run could not be read."} />
      </main>
    );
  }
  const str = (key: string) => (run[key] == null ? null : String(run[key]));
  return (
    <main>
      <Hero tone="history" eyebrow="Agent run" title={<>{str("agent")} <code className="fs-14">{runId}</code></>} testId="agent-run-head"
            actions={<span className="chip neutral">{(str("status") ?? "").toLowerCase()}</span>} />
      <dl className="kv-list kv-inline" data-testid="agent-run-facts">
        <dt>Model</dt><dd>{str("provider") ? `${str("provider")} / ` : ""}{str("model")}</dd>
        <dt>Started by</dt><dd>{str("started_by") ?? "no one (automatic)"}</dd>
        <dt>Started</dt><dd>{(str("started_at") ?? "").slice(0, 16).replace("T", " ")}</dd>
        <dt>Took</dt><dd>{duration(str("started_at") ?? "", str("finished_at"))}</dd>
        <dt>Tokens in / out</dt><dd>{Number(run.input_tokens ?? 0).toLocaleString("en-US")} / {Number(run.output_tokens ?? 0).toLocaleString("en-US")}</dd>
      </dl>
      <RunSteps steps={steps} />
    </main>
  );
}
