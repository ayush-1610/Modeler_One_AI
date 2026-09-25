"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Projects" },
  { href: "/projects/new", label: "+ New project" },
  { href: "/review", label: "Review inbox" },
];

export function Nav() {
  const path = usePathname();
  const is = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden />
        Modeler One
      </div>
      <nav className="nav">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className={is(l.href) ? "active" : ""}>
            {l.label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
