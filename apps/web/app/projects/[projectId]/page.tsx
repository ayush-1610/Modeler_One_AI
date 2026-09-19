import Link from "next/link";

import { Card, RiskChip } from "@/components/ui";
import { COMPOUND, PROJECTS, QUESTIONS } from "@/lib/fixtures";

export default async function ProjectPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const project = PROJECTS.find((p) => p.id === projectId) ?? PROJECTS[0];

  return (
    <main>
      <h1>{project.name}</h1>
      <p className="muted">Compounds and the questions of interest they answer. Each question carries its own ICH M15 assessment table.</p>

      <Card title="Compounds">
        <table>
          <thead><tr><th>Compound</th><th>CPF version</th><th>S0 completeness</th></tr></thead>
          <tbody>
            <tr>
              <td><Link href={`/projects/${project.id}/compounds/${COMPOUND.name}`}>{COMPOUND.name}</Link></td>
              <td>v{COMPOUND.version}</td>
              <td>{Math.round(COMPOUND.completeness * 100)}%</td>
            </tr>
          </tbody>
        </table>
      </Card>

      <Card title="Questions of interest" action={<Link className="btn" href={`/projects/${project.id}/intake`}>Data intake</Link>}>
        <table>
          <thead>
            <tr><th>Question</th><th>Application</th><th>Model risk</th><th>Stage</th><th className="num">Failing criteria</th></tr>
          </thead>
          <tbody>
            {QUESTIONS.map((q) => (
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
