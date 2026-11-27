"use client";

// The page's own bar, at the top of the page panel (the Graphite layout, design-review/DECISIONS.md D-I4 choice 3; it
// replaced the top bar): the menu button on a phone, where the page sits (breadcrumbs), and on the right what waits on
// the person (notifications), Help and whether the API answers. It stays at the top of the window as the page scrolls.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Icon } from "@/components/kit/icons";
import { toast } from "@/components/kit/Toast";
import { useWorkItems } from "@/components/portfolio/useWork";
import { Breadcrumbs } from "@/components/shell/Breadcrumbs";
import { useResource } from "@/lib/hooks";

/** Whether the API answers: its open-escalations read (the one the decision bar polls), every half minute. */
function useApiLive(): boolean | null {
  const esc = useResource("/api/v1/escalations", {}, { select: (d) => d.escalations.length, poll: () => true, interval: 30_000 });
  return esc.data !== null ? true : esc.problem ? false : null;
}

/** Notifications: the first of what waits on this person, each a link to where it is settled; Your work holds them all. */
function Notifications() {
  const items = useWorkItems();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const path = usePathname();
  useEffect(() => { setOpen(false); }, [path]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const n = items?.length ?? 0;
  return (
    <div className="pb-notify" ref={box}>
      <button type="button" ref={button} className="pb-icon" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(!open)}
              aria-label={n ? `Notifications: ${n} waiting on you` : "Notifications"} data-testid="nav-notifications">
        <Icon name="bell" size={18} />{n > 0 && <span className="pb-dot" aria-hidden />}
      </button>
      {open && (
        <div className="popover pb-popover" role="dialog" aria-label="Notifications">
          {items === null ? <p className="muted popover-note">Reading what waits on you…</p>
            : n === 0 ? <p className="muted popover-note">Nothing waits on you.</p>
            : <ul className="popover-list">{items.slice(0, 6).map((it) => (
                <li key={it.key}><Link href={it.href} prefetch={false}>
                  <strong>{it.what}</strong>
                  <span className="muted"> · {it.kind}{it.projectName ? ` · ${it.projectName}` : ""}</span></Link></li>))}</ul>}
          <Link className="popover-foot" href="/work" prefetch={false}>{n > 6 ? `All of Your work (${n})` : "Your work"}</Link>
        </div>
      )}
    </div>
  );
}

export function PageBar({ navOpen, onMenu }: { navOpen: boolean; onMenu: () => void }) {
  const live = useApiLive();
  const queries = useQueryClient();
  const recheck = async () => {
    await queries.refetchQueries({ queryKey: ["/api/v1/escalations"] });
    const state = queries.getQueryState(["/api/v1/escalations", {}, {}]);
    toast(state?.status === "success" ? "The API answers: live data" : "The API does not answer; nothing on screen is current");
  };
  return (
    <header className="pagebar">
      <button type="button" className="pb-icon pb-menu" onClick={onMenu} aria-expanded={navOpen} aria-controls="sidenav"
              aria-label={navOpen ? "Close the navigation" : "Open the navigation"} data-testid="nav-menu">
        <Icon name={navOpen ? "x" : "menu"} size={18} />
      </button>
      <div className="pb-crumbs"><Breadcrumbs /></div>
      <Notifications />
      {/* the user guide, the AI keys path among it (app/help, 2026-11-24) */}
      <Link href="/help" prefetch={false} className="pb-icon" data-testid="nav-help" aria-label="Help"><Icon name="info" size={18} /></Link>
      {/* the API's answer, not a guess: green when its reads answer, grey when they do not; a click asks again */}
      <button type="button" className={`pb-api${live ? " live" : ""}`} onClick={() => void recheck()} data-testid="nav-conn"
              title={live ? "Live: the API answers" : live === false ? "The API does not answer" : "Checking the API"}
              aria-label={live ? "Live: the API answers. Check again" : "The API does not answer. Check again"}>
        <span className="dot" aria-hidden /><span className="pb-api-text">API</span>
      </button>
    </header>
  );
}
