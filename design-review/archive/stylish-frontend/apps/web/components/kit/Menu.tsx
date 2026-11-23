"use client";

// A menu of actions behind one button (plan 2026-11-14, kit Menu): the Inputs head's "Add data". The panel is a popover in
// the browser's top layer, so neither the head (which clips its art) nor a sticky bar covers it. It closes on a choice,
// on Escape, on a click outside and when the page scrolls or resizes (it is placed under its button once, when it
// opens). Its actions are plain buttons in the Tab order: a disclosure, not an ARIA menu with its own arrow keys.
//
// A link elsewhere on the page can open it on one of its actions (`open`: final review round 5, "add a product's
// dissolution data" lands on "Formulation and dissolution files…"): the button is brought into view first (the menu closes
// when the page scrolls), then the menu opens with that action focused; closed again, the focus goes back to its button.

import { useEffect, useId, useRef, type ReactNode } from "react";

export function Menu({ label, testId, children, open, onToggle }: {
  label: ReactNode; testId?: string; children: ReactNode;
  /** open the menu with the action of this test id focused, each time `at` changes */
  open?: { at: number; focus: string } | null;
  /** the menu opened (true) or closed (false) */
  onToggle?: (open: boolean) => void;
}) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  // opened by `open`, not by its button (and when): the focus is handed back to the button when it closes, and the page's
  // own scroll as it lands (a link's navigation) moves it with its button instead of closing it
  const asked = useRef(false);
  const askedAt = useRef(0);
  const said = useRef(onToggle);
  said.current = onToggle;

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
    // whether the focus was in the menu as it closed (read before it hides: the browser then moves it on by itself)
    let inside = false;
    const before = (e: Event) => {
      if ((e as ToggleEvent).newState !== "open") { inside = el.contains(document.activeElement); return; }
      const r = trigger.getBoundingClientRect();
      el.style.top = `${Math.round(r.bottom + 6)}px`;
      el.style.left = `${Math.round(r.left)}px`;
    };
    const scrolled = () => { if (asked.current && Date.now() - askedAt.current < 800) place(); else close(); };
    const toggled = (e: Event) => {
      const opened = (e as ToggleEvent).newState === "open";
      if (opened) {
        place();
        window.addEventListener("scroll", scrolled, { passive: true });
        window.addEventListener("resize", close);
      } else {
        window.removeEventListener("scroll", scrolled);
        window.removeEventListener("resize", close);
        // a menu a link opened (not its button): as it closes, the focus goes to its button, where it is opened again,
        // not back to wherever the browser had it before
        if (asked.current && (inside || document.activeElement === document.body)) trigger.focus({ preventScroll: true });
        asked.current = false;
      }
      said.current?.(opened);
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
      window.removeEventListener("scroll", scrolled);
      window.removeEventListener("resize", close);
    };
  }, []);

  // opened from elsewhere on the page, on one of its actions
  useEffect(() => {
    const el = panel.current;
    const trigger = button.current;
    if (!open || !el || !trigger) return;
    const r = trigger.getBoundingClientRect();
    if (r.top < 0 || r.bottom > window.innerHeight) trigger.scrollIntoView({ block: "nearest", behavior: "instant" });
    // once the scroll has been drawn (a scroll closes the menu)
    const timer = window.setTimeout(() => {
      if (!el.matches(":popover-open")) {
        asked.current = true;
        askedAt.current = Date.now();
        el.showPopover();
      }
      el.querySelector<HTMLElement>(`[data-testid="${CSS.escape(open.focus)}"]`)?.focus();
    }, 120);
    return () => window.clearTimeout(timer);
  }, [open?.at]); // eslint-disable-line react-hooks/exhaustive-deps

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
