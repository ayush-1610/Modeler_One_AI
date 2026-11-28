"use client";

// The console's sidebar (design-review/PRODUCT_SITEMAP.md §1–§4; the Graphite layout, design-review/DECISIONS.md D-I4
// choice 3): fixed and always open on a desktop, a menu below 1024 px, never opened by hover. On top, always: the
// product's mark to Home, Start from proposal, Search (⌘K) and the main links with Your work's count. Under them, from
// the address: the portfolio's, a project's (its four steps with where each stands, its records, Add data) or the
// platform administration's. Help, then the person, at the foot.
//
// Links only the pages that exist (docs/plans/2026-11-23-console-redesign-implementation.md): Home, Your work, Projects,
// Campaigns and Help since slice 2; the project Overview, Compounds and Members since slice 3 (Settings came with the
// sign-in work, 2026-11-24); Agent activity since slice 7.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { createPortal } from "react-dom";

import { Logo } from "@/components/Nav";
import { Icon, type IconName } from "@/components/kit/icons";
import { AddData, stepOf } from "@/components/library/AddData";
import { useWorkCount } from "@/components/portfolio/useWork";
import { Account } from "@/components/shell/Account";
import { Search } from "@/components/shell/Search";
import { useResource } from "@/lib/hooks";
import { STEP_ROUTES, type StepId, type StepRow } from "@/lib/pipeline";
import { stepReason } from "@/lib/words";

type Item = { href: string; label: string; icon?: IconName; active: boolean; testId?: string; sub?: boolean };

function NavItem({ it }: { it: Item }) {
  return (
    <li>
      <Link href={it.href} className={`sn-item${it.sub ? " sub" : ""}`} aria-current={it.active ? "page" : undefined} data-testid={it.testId}
            prefetch={false}>
        <span className="sn-icon" aria-hidden>{it.icon && <Icon name={it.icon} />}</span>
        <span className="sn-text">{it.label}</span>
      </Link>
    </li>
  );
}

function Group({ label, testId, children }: { label: string; testId?: string; children: React.ReactNode }) {
  return (
    <nav className="sn-group" aria-label={label} data-testid={testId}>
      <span className="sn-heading">{label}</span>
      <ul>{children}</ul>
    </nav>
  );
}

/** Always on top: Start from proposal (the product's one primary action), Search, and the main links; Your work with
 *  the count of what waits on this person (Gate 3: the count where the person looks first). */
function MainNav({ path }: { path: string }) {
  const work = useWorkCount();
  const starting = path.startsWith("/projects/start");
  return (
    <nav className="sn-group sn-main" aria-label="Main">
      <Link href="/projects/start" prefetch={false} className="sn-new" aria-current={starting ? "page" : undefined} data-testid="nav-start">
        <Icon name="plus" /><span>Start from proposal</span>
      </Link>
      <Search />
      <ul>
        <NavItem it={{ href: "/", label: "Home", icon: "home", active: path === "/", testId: "nav-home" }} />
        <li>
          <Link href="/work" className="sn-item" aria-current={path.startsWith("/work") ? "page" : undefined} data-testid="top-work" prefetch={false}
                aria-label={work ? `Your work, ${work} waiting` : "Your work"}>
            <span className="sn-icon" aria-hidden><Icon name="checkc" /></span>
            <span className="sn-text">Your work</span>
            {work !== null && work > 0 && <span className="sn-count" aria-hidden>{work}</span>}
          </Link>
        </li>
        <NavItem it={{ href: "/projects", label: "Projects", icon: "folder", active: path === "/projects", testId: "nav-projects" }} />
        <NavItem it={{ href: "/campaigns", label: "Campaigns", icon: "pipeline", active: path.startsWith("/campaigns"), testId: "nav-campaigns" }} />
      </ul>
    </nav>
  );
}

/** The portfolio's own part: the platform's console, for its owner alone. */
function PortfolioNav({ admin }: { admin: boolean }) {
  if (!admin) return null;
  return (
    <Group label="Platform" testId="nav-platform">
      <NavItem it={{ href: "/admin", label: "Admin console", icon: "shield", active: false, testId: "nav-admin" }} />
    </Group>
  );
}

const STEP_LABEL: Record<StepId, string> = { start: "1 · Start", inputs: "2 · Data", review: "3 · Review & sign", run: "4 · Run" };
const STATE_ICON: Record<StepRow["state"], IconName> = { done: "checkc", needs_you: "alert", running: "half", not_started: "dotc" };
const STATE_WORD: Record<StepRow["state"], string> = { done: "done", needs_you: "needs you", running: "running", not_started: "not started" };
const ORDER: StepId[] = ["start", "inputs", "review", "run"];

/** The step a page belongs to, from its address (the step bar's `current`). */
function stepAt(path: string, base: string): StepId | null {
  const rest = path.slice(base.length);
  if (rest.startsWith("/campaigns")) return "run";
  if (rest.startsWith("/start")) return "start";
  if (rest.startsWith("/inputs") || rest.startsWith("/dataroom") || rest.startsWith("/data-plan")) return "inputs";
  if (rest.startsWith("/plan")) return "review";
  return null;
}

/** The project's four steps with where each stands (`GET /steps`), as the step bar had them: until Start is done, a step
 *  after it that has not begun cannot be opened from here (page review 1), and says why on hover. Data holds two pages:
 *  the Data room (what the client sent) and Inputs (what goes into the model), decision G1-1. */
function StepsNav({ projectId, path }: { projectId: string; path: string }) {
  const base = `/projects/${encodeURIComponent(projectId)}`;
  const steps = useResource("/api/v1/projects/{project_id}/steps", { project_id: projectId }, { select: (d) => d.steps });
  const rows: StepRow[] = steps.data ?? ORDER.map((step) => ({ step, label: step, state: "not_started", reasons: [], formulation: null } as unknown as StepRow));
  const known = steps.data !== null;
  const current = stepAt(path, base);
  const start = rows.find((s) => s.step === "start");
  const locked = known && start !== undefined && start.state !== "done";
  return (
    <nav className="sn-group" aria-label="Project steps" data-testid="stepper">
      <span className="sn-heading">Workflow</span>
      <ol>
        {rows.map((s) => {
          // Start's lock is on sending to the model (D4; plan 2026-11-27-one-way-in step 5): Inputs (the Data room) is open
          // before Start is done; Review & sign and Run wait for it
          const shut = locked && s.step !== "start" && s.step !== "inputs" && s.state === "not_started" && current !== s.step;
          const title = s.reasons.length ? s.reasons.map((r) => stepReason(r, s.formulation)).join("\n") : `${STEP_LABEL[s.step]}: ${STATE_WORD[s.state]}`;
          const href = s.step === "inputs" ? `${base}/dataroom` : STEP_ROUTES[s.step](encodeURIComponent(projectId));
          const icon = known ? <span className={`sn-icon state-${s.state}`} role="img" aria-label={STATE_WORD[s.state]}><Icon name={STATE_ICON[s.state]} /></span>
            : <span className="sn-icon" aria-hidden />;
          return (
            <li key={s.step} className={`sn-step ${s.state}`}>
              {/* the step's own row carries its id and state (as the step bar's did): the Data step's two pages sit under it */}
              <div data-testid={`step-${s.step}`} data-state={known ? s.state : undefined}>
              {shut ? (
                <span className="sn-item locked" aria-disabled="true" data-testid={`step-${s.step}-locked`} title={`Finish Start first: ${start!.reasons.join("; ")}`}>
                  <span className="sn-icon" aria-hidden><Icon name="lock" /></span>
                  <span className="sn-text">{STEP_LABEL[s.step]}<span className="sn-state">after Start</span></span>
                </span>
              ) : (
                <Link href={href} prefetch={false} className="sn-item" title={title}
                      aria-current={current === s.step && s.step !== "inputs" ? "page" : undefined}>
                  {icon}<span className="sn-text">{STEP_LABEL[s.step]}</span>
                </Link>
              )}
              </div>
              {s.step === "inputs" && (
                <ul>
                  {/* the Data room's link was always in the sidebar, whatever Start's state (dataroom.spec.ts) */}
                  <NavItem it={{ href: `${base}/dataroom`, label: "Data room", active: path.startsWith(`${base}/dataroom`), testId: "nav-dataroom", sub: true }} />
                  <NavItem it={{ href: `${base}/inputs`, label: "Inputs", active: path.startsWith(`${base}/inputs`), testId: "nav-inputs", sub: true }} />
                  {/* which data the applications require and who provides each (P-13b, read-mostly) */}
                  <NavItem it={{ href: `${base}/data-plan`, label: "Data plan", active: path.startsWith(`${base}/data-plan`), testId: "nav-data-plan", sub: true }} />
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function ProjectNav({ projectId, path }: { projectId: string; path: string }) {
  const base = `/projects/${encodeURIComponent(projectId)}`;
  const name = useResource("/api/v1/projects/{project_id}", { project_id: projectId }, { select: (d) => d.name }).data;
  const [adding, setAdding] = useState(false);
  return (
    <div className="sn-group" data-testid="nav-project">
      <div className="sn-project"><span className="sn-heading">Project</span><strong>{name ?? projectId}</strong></div>
      {/* "Add data" opens a card over the page, at any step (the document library plan) */}
      <button type="button" className="sn-action" data-testid="nav-add-data" onClick={() => setAdding(true)}>
        <span className="sn-icon" aria-hidden><Icon name="plus" /></span><span className="sn-text">Add data</span>
      </button>
      <ul className="sn-top">
        <NavItem it={{ href: base, label: "Overview", icon: "home", active: path === base || path === `${base}/`, testId: "nav-overview" }} />
      </ul>
      <StepsNav projectId={projectId} path={path} />
      <Group label="Records">
        <NavItem it={{ href: `${base}/compounds`, label: "Compounds", icon: "box", active: path.startsWith(`${base}/compounds`), testId: "nav-compounds" }} />
        <NavItem it={{ href: `${base}/library`, label: "Documents", icon: "doc", active: path.startsWith(`${base}/library`), testId: "nav-library" }} />
        <NavItem it={{ href: `${base}/history`, label: "History", icon: "clock", active: path.startsWith(`${base}/history`), testId: "nav-history" }} />
        <NavItem it={{ href: `${base}/agent-activity`, label: "Agent activity", icon: "cpu", active: path.startsWith(`${base}/agent-activity`),
                       testId: "nav-agent-activity" }} />
      </Group>
      {/* the sitemap's PROJECT group: who owns it and who it is shared with (2026-11-24) */}
      <Group label="Project">
        <NavItem it={{ href: `${base}/members`, label: "Members", icon: "users", active: path.startsWith(`${base}/members`), testId: "nav-members" }} />
        <NavItem it={{ href: `${base}/settings`, label: "Settings", icon: "sliders", active: path.startsWith(`${base}/settings`), testId: "nav-settings" }} />
      </Group>
      {/* over the whole page, not inside the navigation (its sticky position would hold the card under the page) */}
      {adding && createPortal(<AddData key={projectId} projectId={projectId} step={stepOf(path)} onClose={() => setAdding(false)} />, document.body)}
    </div>
  );
}

function AdminNav({ path }: { path: string }) {
  const at = (href: string) => (href === "/admin" ? path === "/admin" : path.startsWith(href));
  const items: [string, string, IconName][] = [
    ["/admin", "Overview", "home"], ["/admin/companies", "Companies", "box"], ["/admin/people", "People", "users"],
    ["/admin/usage", "Usage and cost", "chart"],
    ["/admin/models", "Agents and models", "cpu"], ["/admin/keys", "Keys", "key"], ["/admin/limits", "Limits", "gauge"],
    ["/admin/pipeline", "Intake pipeline", "pipeline"], ["/admin/system", "System status", "checkc"],
  ];
  return (
    <Group label="Platform administration">
      {items.map(([href, label, icon]) => <NavItem key={href} it={{ href, label, icon, active: at(href) }} />)}
    </Group>
  );
}

export function SideNav({ open, user }: { open: boolean; user?: string | null }) {
  const path = usePathname();
  const match = /^\/projects\/([^/]+)/.exec(path)?.[1];
  const project = match && match !== "start" ? decodeURIComponent(match) : null;
  // the console's link only for the platform's owner (the API's own answer; it refuses everyone else in any case)
  const admin = useResource("/api/v1/me", {}, { select: (d) => d.admin }).data === true;
  return (
    <aside id="sidenav" className={`sidenav${open ? " open" : ""}`} data-testid="sidebar">
      {/* the top stays in place (Search's list opens over the page from it); the rest scrolls between it and the person */}
      <div className="sn-head">
        <Link href="/" prefetch={false} className="sn-brand" aria-label="Modeler One, home">
          <span className="sn-mark" aria-hidden><Logo size={18} light /></span><span>Modeler One</span>
        </Link>
        <MainNav path={path} />
      </div>
      <div className="sn-scroll">
        {project ? <ProjectNav projectId={project} path={path} />
          // the console's own navigation only for the platform's owner: anyone else at an admin address finds the app's
          // 404 and nothing of the console (admin-console.spec.ts)
          : path.startsWith("/admin") && admin ? <AdminNav path={path} />
          : <PortfolioNav admin={admin} />}
        <nav className="sn-group sn-help" aria-label="Help">
          <ul><NavItem it={{ href: "/help", label: "Help", icon: "info", active: path.startsWith("/help"), testId: "nav-help-guide" }} /></ul>
        </nav>
      </div>
      <div className="sn-foot"><Account user={user} /></div>
    </aside>
  );
}
