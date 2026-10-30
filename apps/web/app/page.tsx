import Link from "next/link";

import { ProjectsTable } from "@/components/projects/ProjectsTable";
import { ApiProblem, Card } from "@/components/ui";
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
        <ProjectsTable projects={projects} />
      </Card>
    </main>
  );
}
