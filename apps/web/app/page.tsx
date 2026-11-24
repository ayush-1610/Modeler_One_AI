import { Home } from "@/components/portfolio/Home";
import { ApiProblem } from "@/components/ui";
import { workItems } from "@/lib/portfolio";
import { getCampaigns, getEscalations, getMe, getPortfolio } from "@/lib/reads";

// Home (P-01, the console redesign's slice 2). The projects come with their steps and owners in one read (R-N03).
export default async function HomePage() {
  const [live, liveCampaigns, liveEscalations, liveMe] = await Promise.all([getPortfolio(), getCampaigns(), getEscalations(), getMe()]);
  const projects = live.data ?? [];
  const me = liveMe.data ? { user_id: liveMe.data.user_id, roles: liveMe.data.roles } : null;
  const work = workItems(projects, liveEscalations.data ?? [], liveCampaigns.data ?? [], me);
  // Only the projects are needed to show the page. Any other read that fails is named with what it leaves out, so a
  // figure is never shown as 0 when it could not be read (one stored campaign the API cannot answer with fails the whole
  // campaign list).
  const partial = [
    liveCampaigns.problem && `The campaigns could not be read (${liveCampaigns.problem}); "Running now" is not shown.`,
    liveEscalations.problem && `The escalations could not be read (${liveEscalations.problem}); they are missing from "Your work".`,
  ].filter((m): m is string => Boolean(m));
  return (
    <main>
      {live.problem && <ApiProblem problem={live.problem} />}
      <Home projects={projects} campaigns={liveCampaigns.data} work={work} me={me?.user_id ?? null}
            notice={!live.problem && partial.length > 0 && (
              <div className="banner warn dash-partial" role="status" data-testid="dash-partial">
                <strong>Part of this page could not be read.</strong>
                <ul>{partial.map((m) => <li key={m}>{m}</li>)}</ul>
              </div>
            )} />
    </main>
  );
}
