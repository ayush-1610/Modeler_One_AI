import { PageShell } from "@/components/kit";
import { Work } from "@/components/portfolio/Work";
import { ApiProblem } from "@/components/ui";
import { workItems } from "@/lib/portfolio";
import { getCampaigns, getEscalations, getMe, getPortfolio } from "@/lib/reads";

// Your work (P-02, the console redesign's slice 2): links only (the owner's decision G1-3).
export default async function WorkPage() {
  const [live, liveCampaigns, liveEscalations, liveMe] = await Promise.all([getPortfolio(), getCampaigns(), getEscalations(), getMe()]);
  const me = liveMe.data ? { user_id: liveMe.data.user_id, roles: liveMe.data.roles } : null;
  const items = workItems(live.data ?? [], liveEscalations.data ?? [], liveCampaigns.data ?? [], me);
  const problem = live.problem ?? liveEscalations.problem ?? liveCampaigns.problem;
  return (
    <main>
    <PageShell title="Your work"
               lede="Everything that waits on you, across your projects. Nothing is decided here: Open goes to the page where it is decided.">
      {problem && <ApiProblem problem={problem} />}
      <Work items={items} />
    </PageShell>
    </main>
  );
}
