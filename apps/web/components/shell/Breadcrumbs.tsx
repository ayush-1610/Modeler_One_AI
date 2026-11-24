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
  plan: [["Review & sign", null]],
  library: [["Documents", null]],
  history: [["History", null]],
};

const ADMIN_PAGES: Record<string, string> = {
  people: "People", usage: "Usage and cost", models: "Agents and models", keys: "Keys", limits: "Limits",
  pipeline: "Intake pipeline", companies: "Company",
};

function crumbsFor(path: string, name: string | null): Crumb[] {
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "projects" && parts[1] === "start") return [["Projects", "/"], ["Start from proposal", null]];
  if (parts[0] === "projects" && parts[1]) {
    const base = `/projects/${encodeURIComponent(parts[1])}`;
    const project: Crumb = [name ?? parts[1], base];
    const page = parts[2];
    if (!page) return [["Projects", "/"], [project[0], null], ["Run", null]];
    if (page === "dataroom" && parts[3] === "report") return [["Projects", "/"], project, ["Data", null], ["Data room", `${base}/dataroom`], ["Evidence report", null]];
    if (page === "compounds" && parts[3]) return [["Projects", "/"], project, ["Compounds", null], [parts[3], null]];
    return [["Projects", "/"], project, ...(PROJECT_PAGES[page] ?? [[page, null]])];
  }
  if (parts[0] === "campaigns" && parts[1]) return [["Projects", "/"], [`Campaign ${parts[1]}`, null]];
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
  const crumbs = path.startsWith("/admin") && !admin ? [] : crumbsFor(path, name);
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
