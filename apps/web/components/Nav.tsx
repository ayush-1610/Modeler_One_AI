"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Projects", group: "" },
  { href: "/review", label: "Review inbox", group: "" },
];

// The pre-loaded example project: real CPF + observed data, runnable from its project page.
const EXAMPLE = [
  { href: "/projects/aciclovir-example", label: "Aciclovir FIH" },
  { href: "/projects/aciclovir-example/compounds/Aciclovir", label: "Compound / CPF" },
  { href: "/projects/aciclovir-example/intake", label: "Data intake" },
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
          <h3>Example project</h3>
          {EXAMPLE.map((l) => (
            <Link key={l.href} href={l.href} className={is(l.href) ? "active" : ""}>
              {l.label}
            </Link>
          ))}
        </div>
      </nav>
    </aside>
  );
}
