"use client";

// Where a page sits (design-review/DESIGN_SYSTEM.md §5.1): every page below Projects says its path, the last part not
// a link. Drawn from the address and, inside a project, the project's name (the API's; its id until it answers).

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useResource } from "@/lib/hooks";

type Crumb = [label: string, href: string | null];

const PROJECT_PAGES: Record<string, Crumb[]> = {
  start: [["Start", null]],
  dataroom: [["Data", null], ["Data room", null]],
  inputs: [["Data", null], ["Inputs", null]],
  "data-plan": [["Data", null], ["Data plan", null]],
  plan: [["Review & sign", null]],
  campaigns: [["Run", null]],
  compounds: [["Compounds", null]],
  members: [["Members", null]],
  settings: [["Settings", null]],
  library: [["Documents", null]],
  history: [["History", null]],
};

const ADMIN_PAGES: Record<string, string> = {
  people: "People", usage: "Usage and cost", models: "Agents and models", keys: "Keys", limits: "Limits",
  pipeline: "Intake pipeline", companies: "Company",
};

function crumbsFor(path: string, name: string | null): Crumb[] {
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const TOP: Record<string, string> = { work: "Your work", campaigns: "Campaigns", help: "Help" };
  if (parts.length === 1 && parts[0] === "projects") return [["Home", "/"], ["Projects", null]];
  if (parts.length === 1 && TOP[parts[0]!]) return [["Home", "/"], [TOP[parts[0]!]!, null]];
  if (parts[0] === "projects" && parts[1] === "start") return [["Projects", "/projects"], ["Start from proposal", null]];
  if (parts[0] === "projects" && parts[1]) {
    const base = `/projects/${encodeURIComponent(parts[1])}`;
    const project: Crumb = [name ?? parts[1], base];
    const page = parts[2];
    if (!page) return [["Projects", "/projects"], [project[0], null]];
    if (page === "dataroom" && parts[3] === "report") return [["Projects", "/projects"], project, ["Data", null], ["Data room", `${base}/dataroom`], ["Evidence report", null]];
    if (page === "compounds" && parts[3]) return [["Projects", "/projects"], project, ["Compounds", `${base}/compounds`], [parts[3], null]];
    return [["Projects", "/projects"], project, ...(PROJECT_PAGES[page] ?? [[page, null]])];
  }
  if (parts[0] === "campaigns" && parts[1]) return [["Campaigns", "/campaigns"], [`Campaign ${parts[1]}`, null]];
  if (parts[0] === "admin") {
    if (!parts[1]) return [["Admin console", null]];
    return [["Admin console", "/admin"], [ADMIN_PAGES[parts[1]] ?? parts[1], null]];
  }
  return [];
}

export function Breadcrumbs() {
  const path = usePathname();
  const id = /^\/projects\/([^/]+)/.exec(path)?.[1];
  const projectId = id && id !== "start" ? decodeURIComponent(id) : null;
  const name = useResource("/api/v1/projects/{project_id}", { project_id: projectId ?? "" }, { enabled: Boolean(projectId), select: (d) => d.name }).data;
  // an admin address names the console only to the platform's owner (anyone else sees the app's 404 and no trace of it)
  const admin = useResource("/api/v1/me", {}, { enabled: path.startsWith("/admin"), select: (d) => d.admin }).data === true;
  // a campaign sits under its project's Run (P-16): its project, read from the campaign, then the project's name
  const cid = /^\/campaigns\/([^/]+)/.exec(path)?.[1];
  const owner = useResource("/api/v1/campaigns/{campaign_id}", { campaign_id: cid ? decodeURIComponent(cid) : "" },
                            { enabled: Boolean(cid), select: (d) => d.project as string }).data;
  const ownerName = useResource("/api/v1/projects/{project_id}", { project_id: owner ?? "" }, { enabled: Boolean(owner), select: (d) => d.name }).data;
  const crumbs = path.startsWith("/admin") && !admin ? []
    : cid && owner ? [["Projects", "/projects"], [ownerName ?? owner, `/projects/${encodeURIComponent(owner)}`],
                      ["Run", `/projects/${encodeURIComponent(owner)}/campaigns`], [`Campaign ${decodeURIComponent(cid)}`, null]] as Crumb[]
    : crumbsFor(path, name);
  if (crumbs.length === 0) return null;
  return (
    <nav className="crumbs" aria-label="Breadcrumbs">
      <ol>
        {crumbs.map(([label, href], i) => {
          const last = i === crumbs.length - 1;
          return (
            <li key={`${i}-${label}`}>
              {href && !last ? <Link href={href} prefetch={false}>{label}</Link> : <span aria-current={last ? "page" : undefined}>{label}</span>}
              {!last && <span className="crumb-sep" aria-hidden>/</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
