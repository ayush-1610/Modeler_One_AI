import Link from "next/link";

import { Hero } from "@/components/kit";
import { ProjectNotices } from "@/components/project/ProjectNotices";
import { ApiProblem, RiskChip, StatusChip } from "@/components/ui";
import { getAudit, getSteps, STEP_ROUTES, type StepRow } from "@/lib/pipeline";
import { NEXT, STEP_NAME, standing, workItems } from "@/lib/portfolio";
import { getArchived, getCampaigns, getEscalations, getMe, getMembers, getProject } from "@/lib/reads";
import { stepReason } from "@/lib/words";

// A project's Overview (P-10, the console redesign's slice 3): where it stands and what to do next. Its address was the
// Run page's; Run is now /projects/{id}/campaigns, one click away in the side navigation and from the steps below.
// Nothing is decided here: each item links to the page where it is done.

const STATE_WORD: Record<StepRow["state"], string> = { done: "Done", needs_you: "Needs you", running: "Running", not_started: "Not started" };
const STATE_CLASS: Record<StepRow["state"], string> = { done: "low", needs_you: "medium", running: "brand", not_started: "neutral" };

export default async function ProjectOverview({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const [live, liveSteps, liveCampaigns, liveAudit, liveMembers, liveEscalations, liveMe, archived] = await Promise.all([
    getProject(projectId), getSteps(projectId), getCampaigns(projectId), getAudit(projectId), getMembers(projectId),
    getEscalations(), getMe(), getArchived(projectId),
  ]);
  const project = live.data;
  if (!project) {
    return (
      <main>
        <Hero title={projectId} />
        <ApiProblem problem={live.problem ?? `Project ${projectId} does not exist.`} />
      </main>
    );
  }
  const base = `/projects/${encodeURIComponent(project.id)}`;
  const steps = liveSteps.data;
  const st = standing(steps);
  const members = liveMembers.data;
  const campaigns = liveCampaigns.data ?? [];
  const latest = campaigns.at(-1) ?? null;
  const me = liveMe.data ? { user_id: liveMe.data.user_id, roles: liveMe.data.roles } : null;
  const work = workItems([{ ...project, steps: steps ?? undefined, owner: members?.owner ?? null, owner_name: members?.owner_name ?? null }],
                         liveEscalations.data ?? [], campaigns, me).filter((w) => w.projectId === project.id);
  const events = (liveAudit.data?.events ?? []).slice(-10).reverse();
  const questions = project.questions ?? [];
  // until Start is done, a later step that has not begun does not open (as in the side navigation; page review 1)
  const startDone = (steps ?? []).find((x) => x.step === "start")?.state === "done";
  const locked = (s: StepRow) => !startDone && s.step !== "start" && s.state === "not_started";

  return (
    <main>
      <Hero title={project.name} testId="overview-head"
            lede={<>{project.compounds.join(", ") || "No compound yet"}{members?.owner_name ? <> · owned by <strong>{members.owner_name}</strong></> : null}</>}
            actions={<>
              <RiskChip rating={project.risk} />
              {st.focus && <Link className="btn primary" href={STEP_ROUTES[st.focus](encodeURIComponent(project.id))} data-testid="overview-next">{st.next}</Link>}
            </>} />
      <ProjectNotices project={project} members={members} archived={archived} />
      {(liveSteps.problem || liveCampaigns.problem) && <ApiProblem problem={(liveSteps.problem ?? liveCampaigns.problem)!} />}

      <div className="home-cols">
        <div>
          <section className="tbl" aria-labelledby="steps-title" data-testid="overview-steps">
            <div className="tbl-head"><h2 id="steps-title">Steps</h2></div>
            <div className="tbl-scroll">
              <table>
                <thead><tr><th scope="col">Step</th><th scope="col">State</th><th scope="col">What it waits on</th><th scope="col">Open</th></tr></thead>
                <tbody>
                  {(steps ?? []).map((s, i) => (
                    <tr key={s.step} data-testid={`overview-step-${s.step}`}>
                      <td><strong>{i + 1} · {STEP_NAME[s.step]}</strong></td>
                      <td><span className={`chip ${STATE_CLASS[s.state]}`}>{STATE_WORD[s.state]}</span></td>
                      <td className="muted">{s.reasons[0] ? stepReason(s.reasons[0], s.formulation) : "—"}</td>
                      <td>{locked(s) ? <span className="muted" data-testid={`overview-step-${s.step}-locked`}>after Start</span>
                        : <Link href={STEP_ROUTES[s.step](encodeURIComponent(project.id))}>{s.state === "done" ? "View" : NEXT[s.step]}</Link>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!steps && <div className="tbl-empty">The steps could not be read.</div>}
          </section>

          <section className="tbl" aria-labelledby="questions-title" data-testid="overview-questions">
            <div className="tbl-head"><h2 id="questions-title">Questions of interest</h2><span className="grow" /><Link href={`${base}/start`}>Edit on Start</Link></div>
            {questions.length === 0 ? <div className="tbl-empty">No question of interest yet: it is set on Start.</div> : (
              <div className="tbl-scroll">
                <table>
                  <thead><tr><th scope="col">Question</th><th scope="col">Application</th><th scope="col">Model risk</th><th scope="col">Stage</th><th scope="col" className="num">Failing criteria</th></tr></thead>
                  <tbody>
                    {questions.map((q) => (
                      <tr key={q.id}>
                        <td>{q.question}</td>
                        <td>{q.application}</td>
                        <td><RiskChip rating={q.modelRisk} /></td>
                        <td>{q.stage}</td>
                        <td className="num">{q.failingCriteria > 0 ? <span className="chip high">{q.failingCriteria}</span> : "0"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="tbl" aria-labelledby="activity-title" data-testid="overview-activity">
            <div className="tbl-head"><h2 id="activity-title">Recent activity</h2><span className="grow" /><Link href={`${base}/history`}>Full history</Link></div>
            {liveAudit.problem ? <div className="tbl-empty">The audit trail could not be read ({liveAudit.problem}).</div>
              : events.length === 0 ? <div className="tbl-empty">Nothing recorded yet.</div> : (
                <div className="tbl-scroll">
                  <table>
                    <thead><tr><th scope="col">When</th><th scope="col">Who</th><th scope="col">What</th><th scope="col">On</th></tr></thead>
                    <tbody>
                      {events.map((e) => (
                        <tr key={e.seq}>
                          <td className="nowrap">{e.occurred_at.slice(0, 16).replace("T", " ")}</td>
                          <td className="nowrap">{e.actor}</td>
                          <td><code>{e.action}</code></td>
                          <td className="muted">{e.resource_type} {e.resource_id}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
          </section>
        </div>
        <div>
          <section className="panel" aria-labelledby="open-title" data-testid="overview-open">
            <div className="panel-head"><h2 id="open-title">Waiting on you</h2></div>
            <div className="panel-body">
              {work.length === 0 ? <p className="muted m-0">Nothing here waits on you.</p> : (
                <ul className="list-plain">
                  {work.map((w) => <li key={w.key}><Link href={w.href}>{w.what}</Link><span className="muted fs-12">{w.step}</span></li>)}
                </ul>
              )}
            </div>
          </section>
          <section className="panel" aria-labelledby="latest-title" data-testid="overview-latest">
            <div className="panel-head"><h2 id="latest-title">Latest campaign</h2><span className="grow" /><Link href={`${base}/campaigns`}>Run</Link></div>
            <div className="panel-body">
              {!latest ? <p className="muted m-0">No campaign yet. It runs once the plan is signed.</p> : (
                <dl className="kv-list">
                  <dt>Campaign</dt><dd><Link href={`/campaigns/${encodeURIComponent(latest.id)}`}><code>{latest.id}</code></Link></dd>
                  <dt>Status</dt><dd><StatusChip status={latest.status} /></dd>
                  <dt>Stage</dt><dd>{latest.currentStage}</dd>
                </dl>
              )}
            </div>
          </section>
          <section className="panel" aria-labelledby="records-title">
            <div className="panel-head"><h2 id="records-title">Records</h2></div>
            <div className="panel-body">
              <ul className="list-plain">
                <li><Link href={`${base}/compounds`}>Compounds</Link><span className="muted fs-12">{project.compounds.length}</span></li>
                <li><Link href={`${base}/library`}>Documents</Link></li>
                <li><Link href={`${base}/history`}>History</Link></li>
                <li><Link href={`${base}/members`}>Members</Link>{members && <span className="muted fs-12">{members.members.length}</span>}</li>
                <li><Link href={`${base}/settings`}>Settings</Link></li>
              </ul>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
