"use client";

// A menu of actions behind one button (plan 2026-11-14, kit Menu): the Inputs head's "Add data". The panel is a popover in
// the browser's top layer, so neither the head (which clips its art) nor a sticky bar covers it. It closes on a choice,
// on Escape, on a click outside and when the page scrolls or resizes (it is placed under its button once, when it
// opens). Its actions are plain buttons in the Tab order: a disclosure, not an ARIA menu with its own arrow keys.

import { useEffect, useId, useRef, type ReactNode } from "react";

export function Menu({ label, testId, children }: { label: ReactNode; testId?: string; children: ReactNode }) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = panel.current;
    const trigger = button.current;
    if (!el || !trigger) return;
    const close = () => { if (el.matches(":popover-open")) el.hidePopover(); };
    // under the button, kept on the screen
    const place = () => {
      const r = trigger.getBoundingClientRect();
      el.style.top = `${Math.round(r.bottom + 6)}px`;
      el.style.left = `${Math.round(Math.max(8, Math.min(r.left, window.innerWidth - el.offsetWidth - 8)))}px`;
    };
    const before = (e: Event) => {
      if ((e as ToggleEvent).newState !== "open") return;
      const r = trigger.getBoundingClientRect();
      el.style.top = `${Math.round(r.bottom + 6)}px`;
      el.style.left = `${Math.round(r.left)}px`;
    };
    const toggled = (e: Event) => {
      if ((e as ToggleEvent).newState === "open") {
        place();
        window.addEventListener("scroll", close, { passive: true });
        window.addEventListener("resize", close);
      } else {
        window.removeEventListener("scroll", close);
        window.removeEventListener("resize", close);
      }
    };
    // a choice closes the menu (after its own click handler has run)
    const chosen = (e: MouseEvent) => { if ((e.target as Element).closest("button:not(:disabled), a")) close(); };
    el.addEventListener("beforetoggle", before);
    el.addEventListener("toggle", toggled);
    el.addEventListener("click", chosen);
    return () => {
      el.removeEventListener("beforetoggle", before);
      el.removeEventListener("toggle", toggled);
      el.removeEventListener("click", chosen);
      window.removeEventListener("scroll", close);
      window.removeEventListener("resize", close);
    };
  }, []);

  return (
    <div className="menu">
      <button ref={button} type="button" className="btn" popoverTarget={id} data-testid={testId}>
        {label} <span className="menu-caret" aria-hidden>▾</span>
      </button>
      <div ref={panel} id={id} popover="auto" className="menu-panel" data-testid={testId ? `${testId}-panel` : undefined}>
        {children}
      </div>
    </div>
  );
}
