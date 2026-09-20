import Link from "next/link";

import { Card, RiskChip } from "@/components/ui";
import { PROJECTS } from "@/lib/fixtures";
import { getProjects } from "@/lib/reads";

export default async function ProjectsPage() {
  const live = await getProjects();
  const projects = live ?? PROJECTS;
  return (
    <main>
      <div className="spread">
        <h1>Projects</h1>
        <Link className="btn primary" href="/projects/new">+ New project</Link>
      </div>
      <p className="muted">PBPK modeling programs on the Open Systems Pharmacology Suite. Each project holds its compounds, questions of interest and campaigns.</p>
      {!live && <div className="banner warn" style={{ marginBottom: 14 }}>Showing sample data — the API is not reachable.</div>}
      <Card>
        <table>
          <thead>
            <tr>
              <th>Project</th>
              <th>Compounds</th>
              <th className="num">Open questions</th>
              <th>Program risk</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td><Link href={`/projects/${p.id}`}>{p.name}</Link></td>
                <td>{p.compounds.join(", ")}</td>
                <td className="num">{p.openQuestions}</td>
                <td><RiskChip rating={p.risk} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </main>
  );
}
