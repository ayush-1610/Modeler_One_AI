"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Projects", group: "" },
  { href: "/review", label: "Review inbox", group: "" },
];

const DEMO = [
  { href: "/projects/example-a", label: "Example-A program" },
  { href: "/projects/example-a/compounds/Example-A", label: "Compound / CPF" },
  { href: "/projects/example-a/intake", label: "Data intake" },
  { href: "/campaigns/camp-101", label: "Campaign monitor" },
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
        <div className="group">
          <h3>Example-A</h3>
          {DEMO.map((l) => (
            <Link key={l.href} href={l.href} className={is(l.href) ? "active" : ""}>
              {l.label}
            </Link>
          ))}
        </div>
      </nav>
    </aside>
  );
}
