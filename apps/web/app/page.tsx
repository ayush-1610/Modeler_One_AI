import Link from "next/link";

import { Card, RiskChip } from "@/components/ui";
import { PROJECTS } from "@/lib/fixtures";

export default function ProjectsPage() {
  return (
    <main>
      <h1>Projects</h1>
      <p className="muted">PBPK modeling programs on the Open Systems Pharmacology Suite. Each project holds its compounds, questions of interest and campaigns.</p>
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
            {PROJECTS.map((p) => (
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
