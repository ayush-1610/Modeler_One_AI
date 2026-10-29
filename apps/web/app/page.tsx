import Link from "next/link";

import { ApiProblem, Card, RiskChip } from "@/components/ui";
import { getProjects } from "@/lib/reads";

export default async function ProjectsPage() {
  const live = await getProjects();
  const projects = live.data ?? [];
  return (
    <main>
      <div className="spread">
        <h1>Projects</h1>
        <Link className="btn primary" href="/projects/start">+ New project</Link>
      </div>
      <p className="muted">PBPK modeling programs on the Open Systems Pharmacology Suite. Each project holds its compounds, questions of interest and campaigns.</p>
      {live.problem && <ApiProblem problem={live.problem} />}
      {!live.problem && projects.length === 0 && (
        <p className="muted">No projects yet. Use <strong>+ New project</strong> to start one from its proposal and the client&apos;s files.</p>
      )}
      <Card>
        <table>
          <thead>
            <tr>
              <th>Project</th>
              <th>Compounds</th>
              <th className="num">Open questions</th>
              <th>Program risk</th>
              <th>Record</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td><Link href={`/projects/${p.id}`}>{p.name}</Link></td>
                <td>{p.compounds.join(", ")}</td>
                <td className="num">{p.openQuestions}</td>
                <td><RiskChip rating={p.risk} /></td>
                <td><Link href={`/projects/${p.id}/history`} data-testid={`project-history-${p.id}`}>History</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </main>
  );
}
