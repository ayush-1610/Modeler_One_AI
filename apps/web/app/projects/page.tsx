import Link from "next/link";

import { ApiProblem, PageShell } from "@/components/kit";
import { ProjectsView } from "@/components/portfolio/ProjectsView";
import { getCampaigns, getMe, getPortfolio } from "@/lib/reads";

// Projects (P-03, the console redesign's slice 2): the table by default, cards as an option; archive and restore here.
export default async function ProjectsPage() {
  const [live, liveCampaigns, liveMe] = await Promise.all([getPortfolio(), getCampaigns(), getMe()]);
  return (
    <main>
    <PageShell title="Projects" lede="The projects you own or that are shared with you."
               actions={<Link className="btn primary" href="/projects/start" data-testid="projects-new">Create project</Link>}>
      {live.problem && <ApiProblem problem={live.problem} />}
      <ProjectsView projects={live.data ?? []} campaigns={liveCampaigns.data ?? []} me={liveMe.data?.user_id ?? null} />
    </PageShell>
    </main>
  );
}
