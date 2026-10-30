"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { createPortal } from "react-dom";

import { ThemeToggle } from "@/components/kit/ThemeToggle";
import { AddData, stepOf } from "@/components/library/AddData";

const LINKS = [
  { href: "/", label: "Projects" },
  { href: "/projects/start", label: "+ Start from proposal" },
  { href: "/review", label: "Review inbox" },
];

/** The sidebar. `user` is the person signed in through Keycloak; with the DEV sign-in there is none to show. */
export function Nav({ user }: { user?: string | null }) {
  const path = usePathname();
  const is = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const project = /^\/projects\/([^/]+)/.exec(path)?.[1];
  const open = project && project !== "start" ? decodeURIComponent(project) : null;
  const [adding, setAdding] = useState(false);
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden />
        Modeler One
      </div>
      <nav className="nav" aria-label="Main">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className={is(l.href) ? "active" : ""} aria-current={is(l.href) ? "page" : undefined}>
            {l.label}
          </Link>
        ))}
      </nav>
      {open && (
        // the open project's own pages (the document library plan): "Add data" opens a card over the page, at any step,
        // directly above the project's library
        <nav className="nav nav-project" aria-label="This project" data-testid="nav-project">
          <span className="nav-heading">This project</span>
          <button type="button" className="nav-action" data-testid="nav-add-data" onClick={() => setAdding(true)}>
            + Add data
          </button>
          <Link href={`/projects/${encodeURIComponent(open)}/library`} data-testid="nav-library"
                className={path.endsWith("/library") ? "active" : ""} aria-current={path.endsWith("/library") ? "page" : undefined}>
            Project Document Library
          </Link>
        </nav>
      )}
      {/* over the whole page, not inside the sidebar (its sticky position would hold the card under the page) */}
      {open && adding && createPortal(
        <AddData key={open} projectId={open} step={stepOf(path)} onClose={() => setAdding(false)} />, document.body)}
      <ThemeToggle />
      {user && (
        <div className="nav-user" data-testid="signed-in">
          Signed in as <strong>{user}</strong>
          {/* a route handler, not a page: a full navigation */}
          <a href="/auth/logout" data-testid="sign-out">Sign out</a>
        </div>
      )}
    </aside>
  );
}
