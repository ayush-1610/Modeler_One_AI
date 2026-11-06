"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { ThemeToggle } from "@/components/kit/ThemeToggle";
import { AddData, stepOf } from "@/components/library/AddData";
import { useResource } from "@/lib/hooks";

// Line icons, drawn on a 24-unit grid with the stroke of the text (plan 2026-11-06-app-design-merge §3 A).
const ICONS = {
  projects: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  start: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M14 3v5h5 M12 12v6 M9 15h6",
  inbox: "M22 12h-6l-2 3h-4l-2-3H2 M5.5 5h13l3.5 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z",
  add: "M12 5v14 M5 12h14",
  library: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20 M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z",
  history: "M12 7v5l3 2 M21 12a9 9 0 1 1-3-6.7 M21 4v5h-5",
  collapse: "M4 6h10 M4 12h6 M4 18h10 M20 8l-4 4 4 4",
} as const;

function Icon({ d }: { d: string }) {
  return (
    <svg className="nav-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={d} /></svg>
  );
}

const COLLAPSED_KEY = "modeler-nav-collapsed";

/** What waits in the Review inbox: open escalations and agent proposals, read again every half minute. */
function useInboxCount(): number {
  const esc = useResource("/api/v1/escalations", {}, { select: (d) => d.escalations.length, poll: () => true, interval: 30_000 });
  const props = useResource("/api/v1/proposals", {}, { select: (d) => d.proposals.length, poll: () => true, interval: 30_000 });
  return (esc.data ?? 0) + (props.data ?? 0);
}

/** The sidebar: the work (projects, a new one, the inbox), the open project's own pages, the person and the theme.
 *  It collapses to a rail of icons and back; the choice is kept in this browser. `user` is the person signed in
 *  through Keycloak; with the DEV sign-in there is none to show. */
export function Nav({ user }: { user?: string | null }) {
  const path = usePathname();
  const is = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const project = /^\/projects\/([^/]+)/.exec(path)?.[1];
  const open = project && project !== "start" ? decodeURIComponent(project) : null;
  const [adding, setAdding] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const inbox = useInboxCount();

  useEffect(() => {
    try { setCollapsed(localStorage.getItem(COLLAPSED_KEY) === "1"); } catch { /* no storage: open */ }
  }, []);
  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    try { if (next) localStorage.setItem(COLLAPSED_KEY, "1"); else localStorage.removeItem(COLLAPSED_KEY); } catch { /* this page only */ }
  };

  const work = [
    { href: "/", label: "Projects", icon: ICONS.projects, active: is("/") || Boolean(open) },
    { href: "/projects/start", label: "Start from proposal", icon: ICONS.start, active: is("/projects/start") },
    { href: "/review", label: "Review inbox", icon: ICONS.inbox, active: is("/review"), badge: inbox },
  ];
  const projectHref = open ? `/projects/${encodeURIComponent(open)}` : "";

  return (
    <aside className={`sidebar${collapsed ? " collapsed" : ""}`} data-testid="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden />
        <span className="nav-text">Modeler One</span>
        <button type="button" className="nav-collapse" onClick={toggle} aria-pressed={collapsed}
                aria-label={collapsed ? "Open the sidebar" : "Collapse the sidebar"} title={collapsed ? "Open the sidebar" : "Collapse the sidebar"}
                data-testid="nav-collapse">
          <Icon d={ICONS.collapse} />
        </button>
      </div>
      <nav className="nav" aria-label="Main">
        <span className="nav-heading">Work</span>
        {work.map((l) => (
          <Link key={l.href} href={l.href} className={l.active ? "active" : ""} aria-current={l.active ? "page" : undefined}
                title={collapsed ? l.label : undefined}>
            <Icon d={l.icon} />
            <span className="nav-text">{l.label}</span>
            {l.badge ? <span className="nav-badge" data-testid="nav-inbox-count" aria-label={`${l.badge} waiting`}>{l.badge}</span> : null}
          </Link>
        ))}
      </nav>
      {open && (
        // the open project's own pages (the document library plan): "Add data" opens a card over the page, at any step,
        // directly above the project's library
        <nav className="nav nav-project" aria-label="This project" data-testid="nav-project">
          <span className="nav-heading">This project</span>
          <button type="button" className="nav-action" data-testid="nav-add-data" onClick={() => setAdding(true)}
                  title={collapsed ? "Add data" : undefined}>
            <Icon d={ICONS.add} /><span className="nav-text">Add data</span>
          </button>
          <Link href={`${projectHref}/library`} data-testid="nav-library" title={collapsed ? "Project Document Library" : undefined}
                className={path.endsWith("/library") ? "active" : ""} aria-current={path.endsWith("/library") ? "page" : undefined}>
            <Icon d={ICONS.library} /><span className="nav-text">Project Document Library</span>
          </Link>
          <Link href={`${projectHref}/history`} data-testid="nav-history" title={collapsed ? "History" : undefined}
                className={path.endsWith("/history") ? "active" : ""} aria-current={path.endsWith("/history") ? "page" : undefined}>
            <Icon d={ICONS.history} /><span className="nav-text">History</span>
          </Link>
        </nav>
      )}
      {/* over the whole page, not inside the sidebar (its sticky position would hold the card under the page) */}
      {open && adding && createPortal(
        <AddData key={open} projectId={open} step={stepOf(path)} onClose={() => setAdding(false)} />, document.body)}
      <div className="nav-foot">
        <ThemeToggle />
        {user && (
          <div className="nav-user" data-testid="signed-in">
            <span className="nav-avatar" aria-hidden>{initials(user)}</span>
            <span className="nav-text">
              Signed in as <strong>{user}</strong>
              {/* a route handler, not a page: a full navigation */}
              <a href="/auth/logout" data-testid="sign-out">Sign out</a>
            </span>
          </div>
        )}
      </div>
    </aside>
  );
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("");
}
