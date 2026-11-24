import { PageShell } from "@/components/kit";
import { Campaigns } from "@/components/portfolio/Campaigns";
import { ApiProblem } from "@/components/ui";
import { getCampaigns, getProjects } from "@/lib/reads";

// Campaigns (P-05, the console redesign's slice 2): every campaign of this person's projects.
export default async function CampaignsPage() {
  const [live, liveProjects] = await Promise.all([getCampaigns(), getProjects()]);
  const names = Object.fromEntries((liveProjects.data ?? []).map((p) => [p.id, p.name]));
  return (
    <main>
    <PageShell title="Campaigns" lede="Every campaign of the projects you are a member of.">
      {live.problem && <ApiProblem problem={live.problem} />}
      <Campaigns campaigns={live.data ?? []} names={names} />
    </PageShell>
    </main>
  );
}
