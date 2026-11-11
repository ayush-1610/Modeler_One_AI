"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useQueryClient } from "@tanstack/react-query";

import { AddData, stepOf } from "@/components/library/AddData";
import { toast } from "@/components/kit/Motion";
import { useResource } from "@/lib/hooks";

// Line icons, drawn on a 24-unit grid with the stroke of the text (plan 2026-11-06-app-design-merge §3 A).
const ICONS = {
  projects: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  start: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M14 3v5h5 M12 12v6 M9 15h6",
  add: "M12 5v14 M5 12h14",
  library: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20 M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z",
  history: "M12 7v5l3 2 M21 12a9 9 0 1 1-3-6.7 M21 4v5h-5",
  admin: "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z M9 12l2 2 4-4",
  collapse: "M4 6h10 M4 12h6 M4 18h10 M20 8l-4 4 4 4",
} as const;

function Icon({ d }: { d: string }) {
  return (
    <svg className="nav-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={d} /></svg>
  );
}

const PIN_KEY = "modeler-nav-pinned";

/** The product's mark: a concentration–time curve over its axes, the observed points in amber. */
function Logo() {
  return (
    <svg className="brand-logo" aria-hidden viewBox="0 0 32 32" width="30" height="30">
      <defs><linearGradient id="mo-g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#2E9BFF" /><stop offset="1" stopColor="#0A4FA8" /></linearGradient></defs>
      <rect width="32" height="32" rx="10" fill="url(#mo-g)" />
      <path d="M6 8v16h20" fill="none" stroke="rgba(255,255,255,0.35)" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M6 23.5C9 23.5 9.5 9 13.5 9c4.5 0 4.5 13 12.5 14" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M6 23.5C9 23.5 9.5 12.5 13.5 12.5c4 0 4.5 9.5 12.5 10.5" fill="none" stroke="rgba(255,255,255,0.45)" strokeWidth="1.2"
            strokeDasharray="1.5 2.2" strokeLinecap="round" />
      <g fill="#FFB340"><circle cx="9.5" cy="16" r="1.7" /><circle cx="13.5" cy="9.5" r="1.7" /><circle cx="19" cy="17" r="1.7" /><circle cx="25" cy="22.5" r="1.7" /></g>
    </svg>
  );
}

/** Whether the API answers: its open-escalations read. This observes the read the decision pop-up (root layout) already
 *  polls, every 15 s (5 s on a running campaign's page); it adds no poll of its own. The review inbox it once counted
 *  for is gone (2026-11-11). */
function useApiLive(): boolean | null {
  const esc = useResource("/api/v1/escalations", {}, { select: (d) => d.escalations.length });
  // the last read failed (not live, even with an earlier answer still cached), the API answered (live), or neither yet
  return esc.problem ? false : esc.data !== null ? true : null;
}

type Item = { href: string; label: string; icon: string; active: boolean; testId?: string };

function NavLink({ l }: { l: Item }) {
  return (
    <Link href={l.href} className={l.active ? "active" : ""} aria-current={l.active ? "page" : undefined} title={l.label} data-testid={l.testId}>
      <span className="nav-glyph"><Icon d={l.icon} /></span>
      <span className="nav-text">{l.label}</span>
    </Link>
  );
}

/** The sidebar (the "Modeler One App" design): a rail of icons that opens over the page when the pointer or the keyboard
 *  is in it, or stays open when pinned (kept in this browser). The work (projects, a new one), the open
 *  project's own pages, and the person. `user` is the person signed in through Keycloak; with the DEV sign-in
 *  there is none to show. */
export function Nav({ user }: { user?: string | null }) {
  const path = usePathname();
  const is = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const project = /^\/projects\/([^/]+)/.exec(path)?.[1];
  const open = project && project !== "start" ? decodeURIComponent(project) : null;
  const [adding, setAdding] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [hover, setHover] = useState(false);
  // opened by the keyboard: only a visible focus opens the panel (a click leaves focus behind and must not hold it open)
  const [keys, setKeys] = useState(false);
  // on a phone the sidebar is a bar along the top; its menu opens over the page (the 2026-11-11 audit, item 3)
  const [menu, setMenu] = useState(false);
  // a new page closes a panel that is not pinned, and the phone's menu
  useEffect(() => { setHover(false); setKeys(false); setMenu(false); }, [path]);
  const live = useApiLive();
  const queries = useQueryClient();
  const recheck = async () => {
    await queries.refetchQueries({ queryKey: ["/api/v1/escalations"] });
    const state = queries.getQueryState(["/api/v1/escalations", {}, {}]);
    toast(state?.status === "success" ? "The API answers: live data" : "The API does not answer; nothing on screen is current");
  };

  useEffect(() => {
    try { setPinned(localStorage.getItem(PIN_KEY) === "1"); } catch { /* no storage: a rail */ }
  }, []);
  const togglePin = () => {
    const next = !pinned;
    setPinned(next);
    try { if (next) localStorage.setItem(PIN_KEY, "1"); else localStorage.removeItem(PIN_KEY); } catch { /* this page only */ }
  };

  const work: Item[] = [
    { href: "/", label: "Projects", icon: ICONS.projects, active: is("/") || Boolean(open) },
    { href: "/projects/start", label: "Start from proposal", icon: ICONS.start, active: is("/projects/start") },
  ];
  // the console's link only for the platform's owner (the API's own answer; it refuses everyone else in any case)
  const admin = useResource("/api/v1/me", {}, { select: (d) => d.admin }).data === true;
  const projectHref = open ? `/projects/${encodeURIComponent(open)}` : "";
  const isOpen = pinned || hover || keys;

  return (
    <aside className={`sidebar${isOpen ? " open" : ""}${pinned ? " pinned" : ""}${menu ? " menu-open" : ""}`} data-testid="sidebar"
           onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
           // choosing a destination closes the panel even with the pointer still on it; it opens again when the pointer
           // leaves and comes back (a panel held open over the next page would cover its left edge)
           onClickCapture={(e) => { if ((e.target as Element).closest("a, .nav-action")) { setHover(false); setKeys(false); setMenu(false); } }}
           onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); e.currentTarget.style.setProperty("--my", `${(e.clientY - r.top).toFixed(0)}px`); }}
           onFocus={(e) => setKeys((e.target as Element).matches(":focus-visible"))}
           onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setKeys(false); }}>
      <div className="brand">
        <Logo />
        <span className="nav-text">Modeler One</span>
        <button type="button" className="nav-pin" onClick={togglePin} aria-pressed={pinned} aria-label="Keep the panel open"
                title="Keep the panel open" data-testid="nav-pin">
          <Icon d={ICONS.collapse} />
        </button>
        <button type="button" className="nav-menu" onClick={() => setMenu(!menu)} aria-expanded={menu} aria-controls="nav-panel"
                aria-label={menu ? "Close the menu" : "Open the menu"} data-testid="nav-menu">
          <Icon d={menu ? "M6 6l12 12 M18 6L6 18" : "M4 7h16 M4 12h16 M4 17h16"} />
        </button>
      </div>
      <div className="nav-panel" id="nav-panel">
      <nav className="nav" aria-label="Main">
        <span className="nav-heading"><span className="nav-heading-text">Work</span></span>
        {work.map((l) => <NavLink key={l.href} l={l} />)}
      </nav>
      {admin && (
        <nav className="nav" aria-label="Platform" data-testid="nav-platform">
          <span className="nav-heading"><span className="nav-heading-text">Platform</span></span>
          <NavLink l={{ href: "/admin", label: "Admin console", icon: ICONS.admin, active: is("/admin"), testId: "nav-admin" }} />
        </nav>
      )}
      {open && (
        // the open project's own pages (the document library plan): "Add data" opens a card over the page, at any step,
        // directly above the project's library
        <nav className="nav nav-project" aria-label="This project" data-testid="nav-project">
          <span className="nav-heading"><span className="nav-heading-text">This project</span></span>
          <button type="button" className="nav-action" data-testid="nav-add-data" onClick={() => setAdding(true)} title="Add data">
            <span className="nav-glyph"><Icon d={ICONS.add} /></span><span className="nav-text">Add data</span>
          </button>
          <NavLink l={{ href: `${projectHref}/library`, label: "Project Document Library", icon: ICONS.library,
                        active: path.endsWith("/library"), testId: "nav-library" }} />
          <NavLink l={{ href: `${projectHref}/history`, label: "History", icon: ICONS.history,
                        active: path.endsWith("/history"), testId: "nav-history" }} />
        </nav>
      )}
      {/* over the whole page, not inside the sidebar (its sticky position would hold the card under the page) */}
      {open && adding && createPortal(
        <AddData key={open} projectId={open} step={stepOf(path)} onClose={() => setAdding(false)} />, document.body)}
      <div className="nav-foot">
        <div className="nav-user" data-testid={user ? "signed-in" : "dev-sign-in"}>
          <span className="nav-avatar" aria-hidden>{user ? initials(user) : "M1"}</span>
          {user ? (
            <span className="nav-text">
              Signed in as <strong>{user}</strong>
              {/* a route handler, not a page: a full navigation */}
              <a href="/auth/logout" data-testid="sign-out">Sign out</a>
            </span>
          ) : (
            <span className="nav-text"><strong>Development sign-in</strong><span className="nav-role">no named user</span></span>
          )}
          {/* the API's answer, not a guess: green when its reads answer, grey when they do not; a click asks again */}
          <button type="button" className={`nav-conn${live ? " live" : ""}`} onClick={() => void recheck()} data-testid="nav-conn"
                  title={live ? "Live: the API answers" : live === false ? "The API does not answer" : "Checking the API"}
                  aria-label={live ? "Live: the API answers. Check again" : "The API does not answer. Check again"} />
        </div>
      </div>
      </div>
    </aside>
  );
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("");
}
