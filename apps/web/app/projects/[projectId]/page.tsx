import Link from "next/link";

import { Card, RiskChip } from "@/components/ui";
import { PROJECTS, QUESTIONS } from "@/lib/fixtures";
import { getProject } from "@/lib/reads";

export default async function ProjectPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const live = await getProject(projectId);
  const project = live ?? PROJECTS.find((p) => p.id === projectId) ?? PROJECTS[0];
  const questions = live?.questions ?? QUESTIONS;
  const compound = project.compounds[0] ?? "Example-A";

  return (
    <main>
      <h1>{project.name}</h1>
      <p className="muted">Compounds and the questions of interest they answer. Each question carries its own ICH M15 assessment table.</p>
      {!live && <div className="banner warn" style={{ marginBottom: 14 }}>Showing sample data — the API is not reachable.</div>}

      <Card title="Compounds">
        <table>
          <thead><tr><th>Compound</th><th>Compounds in scope</th></tr></thead>
          <tbody>
            {project.compounds.map((c) => (
              <tr key={c}>
                <td><Link href={`/projects/${project.id}/compounds/${c}`}>{c}</Link></td>
                <td className="muted">open its CPF →</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Questions of interest" action={<Link className="btn" href={`/projects/${project.id}/intake`}>Data intake</Link>}>
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
