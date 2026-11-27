"use client";

// Search, in the sidebar (the Graphite layout, design-review/DECISIONS.md D-I4 choice 3): "Go to project…", the person's
// open projects found by name or drug as they type. ⌘K (Ctrl K off a Mac) opens it from anywhere; Escape or a click
// elsewhere closes it, the focus back on its button.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Icon } from "@/components/kit/icons";
import { useResource } from "@/lib/hooks";

export function Search() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [mac, setMac] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const path = usePathname();
  const projects = useResource("/api/v1/projects", {}, { enabled: open, select: (d) => d.projects });
  useEffect(() => { setOpen(false); setQ(""); }, [path]);
  // the shortcut's name follows the keyboard: read in the browser, after the first paint (the server cannot know it)
  useEffect(() => { setMac(/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)); }, []);
  useEffect(() => {
    const shortcut = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(true); }
    };
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, []);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const list = (projects.data ?? []).filter((p) => !p.archived)
    .filter((p) => `${p.name} ${p.compounds.join(" ")}`.toLowerCase().includes(q.trim().toLowerCase()));
  const keys = mac ? "⌘K" : "Ctrl K";
  return (
    <div className="switcher" ref={box}>
      <button type="button" ref={button} className="sn-search" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(!open)}
              aria-label="Go to project" aria-keyshortcuts={mac ? "Meta+K" : "Control+K"} data-testid="project-switcher">
        <Icon name="search" /><span className="sn-text">Search</span><kbd aria-hidden>{keys}</kbd>
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
