"use client";

// The console's top bar (design-review/DESIGN_SYSTEM.md §4): the mark and name to Home, "Go to project…", the API's
// state, and the person. The brand's navy, #001B94, with white on it (13.9:1): design option 5, chosen 2026-11-24
// (design-review/DECISIONS.md D-I1).

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Logo } from "@/components/Nav";
import { Icon } from "@/components/kit/icons";
import { toast } from "@/components/kit/Toast";
import { forgetReasons } from "@/components/kit/Reason";
import { useWorkCount } from "@/components/portfolio/useWork";
import { useResource } from "@/lib/hooks";

/** Whether the API answers: its open-escalations read (the one the decision pop-up polls), every half minute. */
function useApiLive(): boolean | null {
  const esc = useResource("/api/v1/escalations", {}, { select: (d) => d.escalations.length, poll: () => true, interval: 30_000 });
  return esc.data !== null ? true : esc.problem ? false : null;
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("");
}

/** "Go to project…": the person's open projects, found by name or drug as they type. */
function ProjectSwitcher() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const path = usePathname();
  const projects = useResource("/api/v1/projects", {}, { enabled: open, select: (d) => d.projects });
  useEffect(() => { setOpen(false); setQ(""); }, [path]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const list = (projects.data ?? []).filter((p) => !p.archived)
    .filter((p) => `${p.name} ${p.compounds.join(" ")}`.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <div className="switcher" ref={box}>
      <button type="button" className="switcher-btn" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(!open)}
              aria-label="Go to project"
              data-testid="project-switcher">
        <Icon name="search" /><span>Go to project…</span><Icon name="chevd" />
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Go to project">
          <input type="search" autoFocus placeholder="Find a project or drug" aria-label="Find a project or drug" value={q}
                 onChange={(e) => setQ(e.target.value)} />
          {projects.problem ? <p className="muted popover-note">{projects.problem}</p>
            : projects.data === null ? <p className="muted popover-note">Reading your projects…</p>
            : list.length === 0 ? <p className="muted popover-note">No project matches.</p>
            : <ul className="popover-list">{list.slice(0, 12).map((p) => (
                <li key={p.id}><Link href={`/projects/${encodeURIComponent(p.id)}`}>{p.name}
                  <span className="muted"> · {p.compounds.join(", ")}</span></Link></li>))}</ul>}
          <Link className="popover-foot" href="/projects" prefetch={false}>All projects</Link>
        </div>
      )}
    </div>
  );
}

/** "Your work (n)": the count of what waits on this person, a link to the list (Gate 3: the count in both places). */
function TopWork() {
  const n = useWorkCount();
  return (
    <Link href="/work" prefetch={false} className="topbar-link" data-testid="top-work" aria-label={n ? `Your work, ${n} waiting` : "Your work"}>
      <Icon name="checkc" /><span className="topbar-link-text">Your work</span>
      {n !== null && n > 0 && <span className="topbar-count">{n}</span>}
    </Link>
  );
}

export function TopBar({ user, navOpen, onMenu }: { user?: string | null; navOpen: boolean; onMenu: () => void }) {
  const live = useApiLive();
  const queries = useQueryClient();
  const recheck = async () => {
    await queries.refetchQueries({ queryKey: ["/api/v1/escalations"] });
    const state = queries.getQueryState(["/api/v1/escalations", {}, {}]);
    toast(state?.status === "success" ? "The API answers: live data" : "The API does not answer; nothing on screen is current");
  };
  return (
    <header className="topbar">
      <button type="button" className="topbar-menu" onClick={onMenu} aria-expanded={navOpen} aria-controls="sidenav"
              aria-label={navOpen ? "Close the navigation" : "Open the navigation"} data-testid="nav-menu">
        <Icon name={navOpen ? "x" : "menu"} size={18} />
      </button>
      <Link href="/" className="topbar-brand" aria-label="Modeler One, home"><Logo size={26} light /><span>Modeler One</span></Link>
      <ProjectSwitcher />
      <span className="grow" />
      <TopWork />
      {/* the user guide, the AI keys path among it (app/help, 2026-11-24) */}
      <Link href="/help" prefetch={false} className="topbar-link" data-testid="nav-help" aria-label="Help"><Icon name="info" /><span className="topbar-link-text">Help</span></Link>
      {/* the API's answer, not a guess: green when its reads answer, grey when they do not; a click asks again */}
      <button type="button" className={`topbar-api${live ? " live" : ""}`} onClick={() => void recheck()} data-testid="nav-conn"
              title={live ? "Live: the API answers" : live === false ? "The API does not answer" : "Checking the API"}
              aria-label={live ? "Live: the API answers. Check again" : "The API does not answer. Check again"}>
        <span className="dot" aria-hidden /><span className="topbar-api-text">API</span>
      </button>
      {user ? (
        <span className="topbar-user">
          <span className="avatar" aria-hidden>{initials(user)}</span>
          <span data-testid="signed-in">Signed in as{" "}
            <Link href="/account" prefetch={false} className="topbar-account" data-testid="nav-account"><strong>{user}</strong></Link></span>
          {/* a route handler, not a page: a full navigation; the reasons this tab kept for the person are forgotten first */}
          <a href="/auth/logout" data-testid="sign-out" onClick={forgetReasons}>Sign out</a>
        </span>
      ) : (
        <span className="topbar-user" data-testid="dev-sign-in">
          <span className="avatar" aria-hidden>M1</span>
          <span><Link href="/account" prefetch={false} className="topbar-account" data-testid="nav-account"><strong>Development sign-in</strong></Link>
            <span className="topbar-role"> · no named user</span></span>
        </span>
      )}
    </header>
  );
}
