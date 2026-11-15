"use client";

// The kit's modal dialog (docs/plans/2026-10-19-p0-p5-redesign.md §7). The signing step-up, an escalation's pop-up and
// the signature confirmation all use it, so they behave the same way: the dialog is named by its title, focus moves in
// when it opens and back to where it was when it closes, Tab stays inside it, and Escape closes it when the caller says
// what closing means. Dialogs nest: Escape and Tab are handled by the innermost one only. Styled by the `.dialog` and
// `.dialog-backdrop` rules (the Review & sign page's drop dialog shares them); sizes and spacing are in kit.css.

import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", "input:not([disabled]):not([type=hidden])", "select:not([disabled])",
  "textarea:not([disabled])", "[tabindex]:not([tabindex='-1'])",
].join(",");
/** The panels of the dialogs open now, the topmost last: only the topmost takes the focus back. */
const OPEN: HTMLElement[] = [];

export function Dialog({ title, onClose, size, above, dismiss, testId, returnFocus, focusKey, children }: {
  title: ReactNode;
  /** What Escape does. Leave it out for a dialog that must be answered with its buttons. */
  onClose?: () => void;
  /** "peek": the source peek, in the centre over the dimmed, still-visible page (plan 2026-11-03 §3.3). */
  size?: "narrow" | "wide" | "peek";
  /** A click on the backdrop closes it too (the source peek: nothing in it is lost by closing). */
  dismiss?: boolean;
  /** Open over another dialog (the signing step-up opens over an escalation's decision). */
  above?: boolean;
  testId?: string;
  /** Where the focus goes when the dialog closes and the element that opened it is gone (a row a decision in the dialog
   *  settled, plan 2026-11-14 slice 4): the list's heading, say. Read when the dialog closes. */
  returnFocus?: () => HTMLElement | null;
  /** What the dialog shows (a queue's item): when it changes and the focus is no longer inside (the button pressed went
   *  with the item it settled), the focus goes back to the panel, so the title is read again and Tab and Escape work. */
  focusKey?: string;
  children: ReactNode;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  const fallback = useRef(returnFocus);
  fallback.current = returnFocus;

  useEffect(() => {
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const me = panel.current;
    me?.focus();   // the panel itself: the title is read first, and no button is one key press from firing
    return () => {
      // back to where it was, if that can still take the focus and lies in the dialog still open under this one (the
      // signing step-up closes over the signature's dialog, final review A11Y-1); else the caller's place; else that
      // dialog's panel. Never the page's body: Tab and Escape would leave the dialog still open
      const under = OPEN.filter((p) => p !== me && p.isConnected).at(-1);
      for (const to of [before, fallback.current?.()]) {
        if (!to?.isConnected || to.matches(":disabled") || (under && !under.contains(to))) continue;
        to.focus();
        if (document.activeElement === to) return;
      }
      under?.focus();
    };
  }, []);

  const shown = useRef(focusKey);
  useEffect(() => {
    if (shown.current === focusKey) return;
    shown.current = focusKey;
    if (panel.current && !panel.current.contains(document.activeElement)) panel.current.focus();
  }, [focusKey]);

  // the safety net (final review A11Y-2): when the focus falls out of the topmost dialog to the page (the focused button
  // went with what it settled, a form closed), the panel takes it back, so Tab and Escape keep working. A focused element
  // that is removed fires no event in every browser, so a change inside the panel is watched as well as a focus leaving.
  useEffect(() => {
    const el = panel.current;
    if (!el) return;
    OPEN.push(el);
    const lost = () => {
      const at = document.activeElement;
      if (OPEN[OPEN.length - 1] === el && el.isConnected && (!at || at === document.body)) el.focus({ preventScroll: true });
    };
    const left = (e: FocusEvent) => { if (!e.relatedTarget) window.setTimeout(lost, 0); };
    const changed = new MutationObserver(() => window.setTimeout(lost, 0));
    el.addEventListener("focusout", left);
    changed.observe(el, { childList: true, subtree: true });
    return () => {
      el.removeEventListener("focusout", left);
      changed.disconnect();
      OPEN.splice(OPEN.indexOf(el), 1);
    };
  }, []);

  // the page behind is held still while any dialog is open, counted so nested dialogs release it only when the last
  // one closes (kit.css: html[data-dialogs]); set and removed here, so it never outlives the dialog
  useEffect(() => {
    const html = document.documentElement;
    html.dataset.dialogs = String(Number(html.dataset.dialogs ?? 0) + 1);
    return () => {
      const left = Number(html.dataset.dialogs ?? 1) - 1;
      if (left > 0) html.dataset.dialogs = String(left);
      else delete html.dataset.dialogs;
    };
  }, []);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape" && close.current) {
      e.stopPropagation();
      close.current();
    } else if (e.key === "Tab" && panel.current) {
      e.stopPropagation();
      const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null);
      if (!items.length) { e.preventDefault(); return; }
      const first = items[0], last = items[items.length - 1], at = document.activeElement;
      if (e.shiftKey && (at === first || at === panel.current)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && at === last) { e.preventDefault(); first.focus(); }
    }
  };

  // over the whole page, at the top of the document: an animated or sticky ancestor would otherwise hold a fixed dialog
  // inside its own box, under the sidebar
  return createPortal(
    <div className={`dialog-backdrop${above ? " step-up" : ""}${size === "peek" ? " peek" : ""}`} data-testid={testId}
         onKeyDown={onKeyDown} onMouseDown={dismiss ? (e) => { if (e.target === e.currentTarget) close.current?.(); } : undefined}>
      <div ref={panel} className={`dialog${size ? ` ${size}` : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <h2 id={titleId} className="dialog-title">{title}</h2>
        {children}
      </div>
    </div>,
    document.body,
  );
}
