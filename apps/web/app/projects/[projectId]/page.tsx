import Link from "next/link";

import { preloadSteps, Stepper } from "@/components/kit/Stepper";
import { OpenDecisionButton } from "@/components/campaign/OpenDecisionButton";
import { RunCampaignButton } from "@/components/RunCampaignButton";
import { MembersPanel } from "@/components/members/MembersPanel";
import { SystemPanel } from "@/components/system/SystemPanel";
import { ApiProblem, Card, RiskChip, StatusChip } from "@/components/ui";
import { serverGet } from "@/lib/api";
import { getSteps } from "@/lib/pipeline";
import { getCampaigns, getProject, getStudies } from "@/lib/reads";
import { Hero } from "@/components/kit";
import { StepBlocked } from "@/components/kit/StepBlocked";

function points(study: { profile?: { times: number[] } | null }) {
  return study.profile?.times?.length ?? 0;
}

export default async function ProjectPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  preloadSteps(projectId); // the step bar's read runs beside the page's own, not after them (audit item 9)
  const [live, liveStudies, liveCampaigns, liveSteps] = await Promise.all([
    getProject(projectId),
    getStudies(projectId),
    getCampaigns(projectId),
    getSteps(projectId),
  ]);
  const project = live.data;
  if (!project) {
    return (
      <main>
        <Hero tone="run" eyebrow="Project" title={projectId} />
        <ApiProblem problem={live.problem ?? `Project ${projectId} does not exist.`} />
      </main>
    );
  }
  const studies = liveStudies.data;
  const campaigns = liveCampaigns.data;
  const questions = project.questions ?? [];
  // The owner's decision 2 (2026-11-11): a campaign starts only from the MAP signed on Review & sign, with the inputs
  // that signature staged. The plan is read only once Review & sign is done (the steps say so from a signed, current MAP);
  // a signed MAP with deviations still waiting for their signature does not run (D-14). The read-only route: a viewer
  // may open Run too, and a page that only shows the plan never uses the canvas route that can write one.
  const reviewDone = liveSteps.data?.find((s) => s.step === "review")?.state === "done";
  const plan = reviewDone ? await serverGet("/api/v1/projects/{project_id}/plan:view", { project_id: projectId }) : null;
  const map = plan?.data?.signed ? plan.data.map : null;
  const pendingDeviations = (plan?.data?.deviations ?? []).filter((d) => !d.signature_id);
  const campaign = map && !pendingDeviations.length ? map.campaign : null;

  return (
    <main>
      <Hero tone="run" eyebrow="Step 4 of 4 · Run" title={<>Run · {project.name}</>}
            lede="Start the modeling campaign from the signed plan and follow it here. The project's compounds, observed studies and members are below."
            actions={<RiskChip rating={project.risk} />} />
      <Stepper projectId={project.id} current="run" />
      {(liveStudies.problem || liveCampaigns.problem) && (
        <ApiProblem problem={(liveStudies.problem ?? liveCampaigns.problem)!} />
      )}

      {liveSteps.problem && <ApiProblem problem={liveSteps.problem} />}
      {plan?.problem && <ApiProblem problem={plan.problem} />}

      {!campaign && !liveSteps.problem && !plan?.problem && (
        // nothing runs without the MAP signed on Review & sign: what it waits on, in words, and the way there
        <StepBlocked projectId={project.id} step="run" waitOn="review" title="A campaign runs from the MAP signed on Review & sign"
                     testId="run-blocked"
                     fallback={(
                       <>
                         <p className="muted">
                           MAP v{map?.map_version ?? "?"} is signed, and {pendingDeviations.length} deviation
                           {pendingDeviations.length === 1 ? " waits" : "s wait"} for the MIDD lead&apos;s signature. A campaign
                           starts once they are signed into a new MAP version.
                         </p>
                         <Link className="btn primary" href={`/projects/${project.id}/plan`} data-testid="step-blocked-go">
                           Go to Review &amp; sign</Link>
                       </>
                     )} />
      )}

      {campaign && map && (
        <Card title="Run a modeling campaign" action={<span className="muted">MS-01 · S0 → S7</span>}>
          <p className="muted mt-0" data-testid="run-from-map">
            Starts from MAP v{map.map_version ?? map.version}, signed on Review &amp; sign
            ({map.map_sha256.slice(0, 12)}), with the inputs that signature staged. The stage loop runs on the OSP
            engine: it builds the model, simulates, scores it against the acceptance tier, and either passes or stops to
            ask you for a signed decision, on whatever page you are on. A change to the plan is made and signed on{" "}
            <Link href={`/projects/${project.id}/plan`}>Review &amp; sign</Link>.
          </p>
          <RunCampaignButton projectId={project.id} campaign={campaign} />
        </Card>
      )}

      <div className="cols-2">
        <Card title="Compounds">
          <table>
            <thead><tr><th>Compound</th><th>Parameter framework</th></tr></thead>
            <tbody>
              {project.compounds.map((c) => (
                <tr key={c}>
                  <td><Link href={`/projects/${project.id}/compounds/${c}`}>{c}</Link></td>
                  <td className="muted">parameter framework</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="Observed studies" action={<Link className="btn" href={`/projects/${project.id}/inputs?tab=studies`}>Add data</Link>}>
          {studies && studies.length > 0 ? (
            <table>
              <thead><tr><th>Study</th><th>Route</th><th className="num">Dose</th><th className="num">Points</th></tr></thead>
              <tbody>
                {/* a summary: the first ten; the whole list, sortable and filtered, is on Inputs (audit item 11) */}
                {studies.slice(0, 10).map((s) => (
                  <tr key={s.study_id}>
                    <td><strong className="overflow-anywhere">{s.study_id}</strong></td>
                    <td>{s.route?.replace("_", " ") ?? "—"}</td>
                    <td className="num">{s.dose_mg} mg</td>
                    <td className="num">{points(s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {studies && studies.length > 10 && (
            <p className="muted m-8-0-0 fs-13" data-testid="overview-studies-more">
              10 of {studies.length} studies shown.{" "}
              <Link href={`/projects/${project.id}/inputs?tab=studies`}>All {studies.length} studies on Inputs →</Link>
            </p>
          )}
          {studies && studies.length > 0 ? null : (
            <p className="muted m-0">
              No observed data yet. Use <strong>Add data</strong> to upload a clinical profile — a campaign
              needs at least one study to fit and validate against.
            </p>
          )}
        </Card>
      </div>

      <SystemPanel projectId={project.id} />

      <Card title="Campaigns">
        {campaigns && campaigns.length > 0 ? (
          <table>
            <thead><tr><th>Campaign</th><th>Status</th><th>Current stage</th><th>Compound</th></tr></thead>
            <tbody>
              {campaigns.map((c) => (
                <tr key={c.id}>
                  <td><Link href={`/campaigns/${c.id}`}><code>{c.id}</code></Link></td>
                  <td>
                    {c.status ? <StatusChip status={c.status} /> : "—"}
                    {/* the waiting decision, one click away from its row (it may have been put off) */}
                    {c.status === "ESCALATED" && <> <OpenDecisionButton campaignId={c.id} /></>}
                  </td>
                  <td>{c.currentStage}</td>
                  <td>{c.compound}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted m-0">
            No campaigns yet — run one above and this table will fill in as it progresses.
          </p>
        )}
      </Card>

      <Card title="Questions of interest">
        <table>
          <thead>
            <tr><th>Question</th><th>Application</th><th>Model risk</th><th>Stage</th><th className="num">Failing criteria</th></tr>
          </thead>
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
      </Card>

      <MembersPanel projectId={project.id} />
    </main>
  );
}
