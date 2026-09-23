import Link from "next/link";

import { RunCampaignButton } from "@/components/RunCampaignButton";
import { Card, RiskChip, StatusChip } from "@/components/ui";
import { PROJECTS, QUESTIONS } from "@/lib/fixtures";
import { getCampaigns, getProject, getStudies } from "@/lib/reads";

function points(study: { profile?: { times: number[] } }) {
  return study.profile?.times?.length ?? 0;
}

export default async function ProjectPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const [live, studies, campaigns] = await Promise.all([
    getProject(projectId),
    getStudies(projectId),
    getCampaigns(projectId),
  ]);
  const project = live ?? PROJECTS.find((p) => p.id === projectId) ?? PROJECTS[0];
  const questions = live?.questions ?? QUESTIONS;
  const compound = project.compounds[0] ?? "";
  const question = questions[0];
  const runnable = Boolean(live && question && compound && studies && studies.length > 0);

  return (
    <main>
      <div className="spread">
        <h1>{project.name}</h1>
        <RiskChip rating={project.risk} />
      </div>
      <p className="muted">Compounds and the questions of interest they answer. Each question carries its own ICH M15 assessment table.</p>
      {!live && <div className="banner warn" style={{ marginBottom: 14 }}>Showing sample data — the API is not reachable.</div>}

      {runnable && (
        <Card title="Run a modeling campaign" action={<span className="muted">MS-01 · S0 → S1</span>}>
          <p className="muted" style={{ marginTop: 0 }}>
            Generates the Model Analysis Plan from this project&apos;s CPF and {studies!.length} observed
            study(ies), records the Part 11 signature, then runs the stage loop on the OSP engine — building
            the model, simulating, scoring it against the acceptance tier, and either passing or escalating
            to the review inbox.
          </p>
          <RunCampaignButton projectId={project.id} questionId={question!.id} compound={compound} />
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

        <Card title="Observed studies" action={<Link className="btn" href={`/projects/${project.id}/intake`}>Add data</Link>}>
          {studies && studies.length > 0 ? (
            <table>
              <thead><tr><th>Study</th><th>Route</th><th className="num">Dose</th><th className="num">Points</th></tr></thead>
              <tbody>
                {studies.map((s) => (
                  <tr key={s.study_id}>
                    <td><code>{s.study_id}</code></td>
                    <td>{s.route.replace("_", " ")}</td>
                    <td className="num">{s.dose_mg} mg</td>
                    <td className="num">{points(s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted" style={{ margin: 0 }}>
              No observed data yet. Use <strong>Add data</strong> to upload a clinical profile — a campaign
              needs at least one study to fit and validate against.
            </p>
          )}
        </Card>
      </div>

      <Card title="Campaigns">
        {campaigns && campaigns.length > 0 ? (
          <table>
            <thead><tr><th>Campaign</th><th>Status</th><th>Current stage</th><th>Compound</th></tr></thead>
            <tbody>
              {campaigns.map((c) => (
                <tr key={c.id}>
                  <td><Link href={`/campaigns/${c.id}`}><code>{c.id}</code></Link></td>
                  <td>{c.status ? <StatusChip status={c.status} /> : "—"}</td>
                  <td>{c.currentStage}</td>
                  <td>{c.compound}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted" style={{ margin: 0 }}>
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
    </main>
  );
}
