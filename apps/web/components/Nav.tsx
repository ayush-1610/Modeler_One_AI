"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ThemeToggle } from "@/components/kit/ThemeToggle";

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
        // the open project's own pages (the document library plan: its library, and "Add data" above it, in PR 2)
        <nav className="nav nav-project" aria-label="This project" data-testid="nav-project">
          <span className="nav-heading">This project</span>
          <Link href={`/projects/${encodeURIComponent(open)}/library`} data-testid="nav-library"
                className={path.endsWith("/library") ? "active" : ""} aria-current={path.endsWith("/library") ? "page" : undefined}>
            Project Document Library
          </Link>
        </nav>
      )}
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
