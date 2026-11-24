"use client";

// The console's side navigation (design-review/PRODUCT_SITEMAP.md §1–§4): fixed and always open on a desktop, a menu
// below 1024 px, never opened by hover. Three contexts, from the address: the portfolio, a project (its four steps with
// where each stands, its records, Add data), and the platform's administration.
//
// Slice 1 of the redesign (docs/plans/2026-11-23-console-redesign-implementation.md) links only the pages that exist:
// Your work, Campaigns, Help, the project Overview, Members, Settings, Compounds and Agent activity join with their slices.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { createPortal } from "react-dom";

import { Icon, type IconName } from "@/components/kit/icons";
import { AddData, stepOf } from "@/components/library/AddData";
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

function PortfolioNav({ path, admin }: { path: string; admin: boolean }) {
  return (
    <>
      <nav className="sn-group" aria-label="Main">
        <span className="sn-heading">Modeler One</span>
        <ul>
          <NavItem it={{ href: "/", label: "Projects", icon: "folder", active: path === "/" }} />
          <NavItem it={{ href: "/projects/start", label: "Start from proposal", icon: "fileplus", active: path.startsWith("/projects/start") }} />
        </ul>
      </nav>
      {admin && (
        <Group label="Platform" testId="nav-platform">
          <NavItem it={{ href: "/admin", label: "Admin console", icon: "shield", active: false, testId: "nav-admin" }} />
        </Group>
      )}
    </>
  );
}

const STEP_LABEL: Record<StepId, string> = { start: "1 · Start", inputs: "2 · Data", review: "3 · Review & sign", run: "4 · Run" };
const STATE_ICON: Record<StepRow["state"], IconName> = { done: "checkc", needs_you: "alert", running: "half", not_started: "dotc" };
const STATE_WORD: Record<StepRow["state"], string> = { done: "done", needs_you: "needs you", running: "running", not_started: "not started" };
const ORDER: StepId[] = ["start", "inputs", "review", "run"];

/** The step a page belongs to, from its address (the step bar's `current`). */
function stepAt(path: string, base: string): StepId | null {
  const rest = path.slice(base.length);
  if (rest === "" || rest === "/") return "run";
  if (rest.startsWith("/start")) return "start";
  if (rest.startsWith("/inputs") || rest.startsWith("/dataroom")) return "inputs";
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
          const shut = locked && s.step !== "start" && s.state === "not_started" && current !== s.step;
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
                  {!shut && <NavItem it={{ href: `${base}/inputs`, label: "Inputs", active: path.startsWith(`${base}/inputs`), testId: "nav-inputs", sub: true }} />}
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
    <div data-testid="nav-project">
      <Link href="/" className="sn-back"><Icon name="chevl" size={14} /> All projects</Link>
      <div className="sn-project"><strong>{name ?? projectId}</strong></div>
      {/* "Add data" opens a card over the page, at any step (the document library plan) */}
      <button type="button" className="sn-action" data-testid="nav-add-data" onClick={() => setAdding(true)}>
        <span className="sn-icon" aria-hidden><Icon name="plus" /></span><span className="sn-text">Add data</span>
      </button>
      <StepsNav projectId={projectId} path={path} />
      <Group label="Records">
        <NavItem it={{ href: `${base}/library`, label: "Documents", icon: "doc", active: path.startsWith(`${base}/library`), testId: "nav-library" }} />
        <NavItem it={{ href: `${base}/history`, label: "History", icon: "clock", active: path.startsWith(`${base}/history`), testId: "nav-history" }} />
      </Group>
      {/* over the whole page, not inside the navigation (its sticky position would hold the card under the page) */}
      {adding && createPortal(<AddData key={projectId} projectId={projectId} step={stepOf(path)} onClose={() => setAdding(false)} />, document.body)}
    </div>
  );
}

function AdminNav({ path }: { path: string }) {
  const at = (href: string) => (href === "/admin" ? path === "/admin" || path.startsWith("/admin/companies") : path.startsWith(href));
  const items: [string, string, IconName][] = [
    ["/admin", "Overview", "home"], ["/admin/people", "People", "users"], ["/admin/usage", "Usage and cost", "chart"],
    ["/admin/models", "Agents and models", "cpu"], ["/admin/keys", "Keys", "key"], ["/admin/limits", "Limits", "gauge"],
    ["/admin/pipeline", "Intake pipeline", "pipeline"],
  ];
  return (
    <>
      <Link href="/" className="sn-back"><Icon name="chevl" size={14} /> Modeler One</Link>
      <Group label="Platform administration">
        {items.map(([href, label, icon]) => <NavItem key={href} it={{ href, label, icon, active: at(href) }} />)}
      </Group>
    </>
  );
}

export function SideNav({ open }: { open: boolean }) {
  const path = usePathname();
  const match = /^\/projects\/([^/]+)/.exec(path)?.[1];
  const project = match && match !== "start" ? decodeURIComponent(match) : null;
  // the console's link only for the platform's owner (the API's own answer; it refuses everyone else in any case)
  const admin = useResource("/api/v1/me", {}, { select: (d) => d.admin }).data === true;
  return (
    <aside id="sidenav" className={`sidenav${open ? " open" : ""}`} data-testid="sidebar">
      {project ? <ProjectNav projectId={project} path={path} />
        // the console's own navigation only for the platform's owner: anyone else at an admin address finds the app's
        // 404 and nothing of the console (admin-console.spec.ts)
        : path.startsWith("/admin") && admin ? <AdminNav path={path} />
        : <PortfolioNav path={path} admin={admin} />}
    </aside>
  );
}
