"use client";

// The console's side panel (design-review/DESIGN_SYSTEM.md §5.7; the console redesign's slice 4b; the owner's Gate 3
// answer and decision D-I2): one item's detail on the right, beside the list it was opened from, which stays usable. Not
// a dialog: nothing behind it is blocked, and a wide window makes room for it instead of covering the page. Previous and
// Next move between the list's items; Escape (outside a dialog inside it) and Close put it away.

import { useEffect, useRef, type ReactNode } from "react";

import { Icon } from "@/components/kit/icons";

export function SidePanel({ title, label, onClose, onPrev, onNext, position, children, testId }: {
  title: ReactNode;
  /** The panel's accessible name ("Study OJ-101"). */
  label: string;
  onClose: () => void;
  onPrev?: (() => void) | null;
  onNext?: (() => void) | null;
  /** "2 of 5" */
  position?: string;
  children: ReactNode;
  testId?: string;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const panel = useRef<HTMLElement>(null);
  // the panel's own name takes focus when it opens or shows another item, so a keyboard and a screen reader follow it
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [label]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || !panel.current) return;
      // a dialog over the page (a signature, a confirmation) answers its own Escape
      if (document.querySelector(".dialog-backdrop")) return;
      if (panel.current.contains(document.activeElement)) { e.preventDefault(); onClose(); }
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [onClose]);
  return (
    <aside ref={panel} className="spanel" aria-label={label} data-testid={testId}>
      <header className="spanel-head">
        <h2 ref={heading} tabIndex={-1}>{title}</h2>
        {position && <span className="muted fs-12">{position}</span>}
        <span className="grow" />
        {onPrev !== undefined && (
          <button type="button" className="btn small ghost" onClick={onPrev ?? undefined} disabled={!onPrev} aria-label="Previous" data-testid="side-panel-prev">
            <Icon name="chevl" />
          </button>
        )}
        {onNext !== undefined && (
          <button type="button" className="btn small ghost" onClick={onNext ?? undefined} disabled={!onNext} aria-label="Next" data-testid="side-panel-next">
            <Icon name="chevr" />
          </button>
        )}
        <button type="button" className="btn small ghost" onClick={onClose} aria-label="Close the panel" data-testid="side-panel-close">
          <Icon name="x" />
        </button>
      </header>
      <div className="spanel-body">{children}</div>
    </aside>
  );
}
