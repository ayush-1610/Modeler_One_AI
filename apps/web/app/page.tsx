import { Dashboard, type DashboardProject, type Attention } from "@/components/dashboard/Dashboard";
import { ApiProblem } from "@/components/ui";
import { getSteps, STEP_ROUTES, type StepRow } from "@/lib/pipeline";
import { getCampaigns, getEscalations, getProjects, getProposals } from "@/lib/reads";

// What a project's next action is called, by the step it waits at (plan 2026-11-06-app-design-merge §3 A).
const NEXT: Record<StepRow["step"], string> = {
  start: "Confirm the brief", inputs: "Finish the inputs", review: "Sign the MAP", run: "Run the campaign",
};

/** Where a project stands, read from its four steps: the step that waits on a person first, then one that runs. */
function standing(steps: StepRow[] | null): Pick<DashboardProject, "state" | "focus" | "next" | "reason"> {
  if (!steps) return { state: "unknown", focus: null, next: "Open the project", reason: null };
  const waiting = steps.find((s) => s.state === "needs_you");
  const running = steps.find((s) => s.state === "running");
  if (waiting) return { state: "needs_you", focus: waiting.step, next: NEXT[waiting.step], reason: waiting.reasons[0] ?? null };
  if (running) return { state: "running", focus: running.step, next: "Watch the run", reason: running.reasons[0] ?? null };
  if (steps.every((s) => s.state === "done")) return { state: "done", focus: "run", next: "Open the results", reason: null };
  const first = steps.find((s) => s.state !== "done") ?? steps[0]!;
  return { state: "not_started", focus: first.step, next: NEXT[first.step], reason: first.reasons[0] ?? null };
}

export default async function DashboardPage() {
  const [live, liveCampaigns, liveEscalations, liveProposals] = await Promise.all([
    getProjects(), getCampaigns(), getEscalations(), getProposals(),
  ]);
  const projects = live.data ?? [];
  // the steps are read per project (no list route carries them yet: plan §4, gap 3); archived projects are not asked
  const liveSteps = await Promise.all(projects.map((p) => (p.archived ? Promise.resolve(null) : getSteps(p.id))));
  const steps = liveSteps.map((s) => s?.data ?? null);
  const campaigns = liveCampaigns.data ?? [];
  const escalations = liveEscalations.data ?? [];
  const proposals = liveProposals.data ?? [];

  const rows: DashboardProject[] = projects.map((p, i) => {
    const st = standing(steps[i] ?? null);
    return {
      id: p.id, name: p.name, compounds: p.compounds, openQuestions: p.openQuestions, risk: p.risk,
      archived: Boolean(p.archived), steps: (steps[i] ?? []).map((s) => ({ step: s.step, label: s.label, state: s.state })),
      ...st,
      href: st.focus ? STEP_ROUTES[st.focus](p.id) : `/projects/${p.id}`,
      running: campaigns.filter((c) => c.project === p.id && c.status === "RUNNING").length,
    };
  });

  const projectOf = new Map(campaigns.map((c) => [c.id, projects.find((p) => p.id === c.project)?.name ?? c.project]));
  const attention: Attention[] = [
    ...escalations.map((e) => ({
      key: `esc-${e.id}`, tone: "fail" as const, href: "/review",
      title: `Escalation at ${e.stage} · ${projectOf.get(e.campaignId) ?? e.campaignId}`,
      detail: e.reasonCode.replace(/_/g, " ").toLowerCase(),
    })),
    ...(proposals.length > 0
      ? [{ key: "proposals", tone: "warn" as const, href: "/review", title: `${proposals.length} parameter proposal${proposals.length === 1 ? "" : "s"} to review`,
           detail: "agent values with their citations" }]
      : []),
    ...rows.filter((r) => !r.archived && r.state === "needs_you").map((r) => ({
      key: `step-${r.id}`, tone: "warn" as const, href: r.href, title: `${r.next} · ${r.name}`, detail: r.reason ?? "waiting on you",
    })),
  ];

  // Only the projects are needed to show the page. Any other read that fails is named with what it leaves out, so a
  // figure is never shown as 0 when it could not be read (one stored campaign the API cannot answer with fails the whole
  // campaign list).
  const partial = [
    liveCampaigns.problem && `The campaigns could not be read (${liveCampaigns.problem}); "Running now" is not shown.`,
    liveEscalations.problem && `The escalations could not be read (${liveEscalations.problem}); they are missing from "Needs your attention".`,
    liveProposals.problem && `The parameter proposals could not be read (${liveProposals.problem}).`,
    liveSteps.some((s) => s?.problem) && `The steps of ${liveSteps.filter((s) => s?.problem).length} project(s) could not be read; their cards say "Steps not read".`,
  ].filter((m): m is string => Boolean(m));
  return (
    <main>
      {live.problem && <ApiProblem problem={live.problem} />}
      <Dashboard projects={rows} attention={attention}
                 runningCampaigns={liveCampaigns.data ? campaigns.filter((c) => c.status === "RUNNING").length : null}
                 tableProjects={projects}
                 notice={!live.problem && partial.length > 0 && (
                   <div className="banner warn dash-partial" role="status" data-testid="dash-partial">
                     <strong>Part of the dashboard could not be read.</strong>
                     <ul>{partial.map((m) => <li key={m}>{m}</li>)}</ul>
                   </div>
                 )} />
    </main>
  );
}
