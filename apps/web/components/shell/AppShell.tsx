"use client";

// The console's frame (design-review/DESIGN_SYSTEM.md §4; the Graphite layout, design-review/DECISIONS.md D-I4 choice 3):
// the sidebar on the grey canvas, beside the page as one white rounded panel with its own bar on top. On a phone the
// sidebar is a menu the page bar opens; a new page, or Escape, closes it.

import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { PageBar } from "@/components/shell/PageBar";
import { SideNav } from "@/components/shell/SideNav";

export function AppShell({ user, children }: { user?: string | null; children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const path = usePathname();
  useEffect(() => { setNavOpen(false); }, [path]);
  useEffect(() => {
    if (!navOpen) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setNavOpen(false); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [navOpen]);
  return (
    <div className="console">
      <SideNav open={navOpen} user={user} />
      <div className="page-frame">
        <PageBar navOpen={navOpen} onMenu={() => setNavOpen((o) => !o)} />
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
