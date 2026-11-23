"use client";

// The console's frame (design-review/DESIGN_SYSTEM.md §4): the top bar over the side navigation and the page. On a phone
// the navigation is a menu the top bar opens; a new page closes it.

import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { SideNav } from "@/components/shell/SideNav";
import { TopBar } from "@/components/shell/TopBar";

export function AppShell({ user, children }: { user?: string | null; children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const path = usePathname();
  useEffect(() => { setNavOpen(false); }, [path]);
  return (
    <div className="console">
      <TopBar user={user} navOpen={navOpen} onMenu={() => setNavOpen((o) => !o)} />
      <div className="console-body">
        <SideNav open={navOpen} />
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
