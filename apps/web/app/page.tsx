import { Home } from "@/components/portfolio/Home";
import { ApiProblem } from "@/components/kit";
import { workItems } from "@/lib/portfolio";
import { getCampaignList, getEscalations, getMe, getPortfolio } from "@/lib/reads";

// Home (P-01, the console redesign's slice 2). The projects come with their steps and owners in one read (R-N03).
export default async function HomePage() {
  const [live, liveCampaigns, liveEscalations, liveMe] = await Promise.all([getPortfolio(), getCampaignList(), getEscalations(), getMe()]);
  const projects = live.data ?? [];
  const campaigns = liveCampaigns.data?.campaigns ?? null;
  const unreadable = liveCampaigns.data?.unreadable ?? [];
  const me = liveMe.data ? { user_id: liveMe.data.user_id, roles: liveMe.data.roles } : null;
  const work = workItems(projects, liveEscalations.data ?? [], campaigns ?? [], me);
  // Only the projects are needed to show the page. Any other read that fails is named with what it leaves out, so a
  // figure is never shown as 0 when it could not be read. A campaign stored in a shape this version cannot read no longer
  // fails the whole list (the server, 2026-11-24): the API names it, and so does the page.
  const partial = [
    liveCampaigns.problem && `The campaigns could not be read (${liveCampaigns.problem}); "Running now" is not shown.`,
    unreadable.length > 0 && `${unreadable.length === 1 ? "One campaign was" : `${unreadable.length} campaigns were`} stored in a shape this version cannot read, so ${unreadable.length === 1 ? "it is" : "they are"} not counted: ${unreadable.map((u) => `${u.id} (${u.problems.join("; ")})`).join(", ")}.`,
    liveEscalations.problem && `The escalations could not be read (${liveEscalations.problem}); they are missing from "Your work".`,
  ].filter((m): m is string => Boolean(m));
  return (
    <main>
      {live.problem && <ApiProblem problem={live.problem} />}
      <Home projects={projects} campaigns={campaigns} work={work} me={me?.user_id ?? null}
            notice={!live.problem && partial.length > 0 && (
              <div className="banner warn dash-partial" role="status" data-testid="dash-partial">
                <strong>Part of this page could not be read.</strong>
                <ul>{partial.map((m) => <li key={m}>{m}</li>)}</ul>
              </div>
            )} />
    </main>
  );
}
