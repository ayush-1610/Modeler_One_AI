"use client";

// The kit's modal dialog (docs/plans/2026-10-19-p0-p5-redesign.md §7). The signing step-up, an escalation's pop-up and
// the signature confirmation all use it, so they behave the same way: the dialog is named by its title, focus moves in
// when it opens and back to where it was when it closes, Tab stays inside it, and Escape closes it when the caller says
// what closing means. Dialogs nest: Escape and Tab are handled by the innermost one only. Styled by the `.dialog` and
// `.dialog-backdrop` rules (the Review & sign page's drop dialog shares them); sizes and spacing are in kit.css.

import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", "input:not([disabled]):not([type=hidden])", "select:not([disabled])",
  "textarea:not([disabled])", "[tabindex]:not([tabindex='-1'])",
].join(",");

export function Dialog({ title, onClose, size, above, testId, children }: {
  title: ReactNode;
  /** What Escape does. Leave it out for a dialog that must be answered with its buttons. */
  onClose?: () => void;
  size?: "narrow" | "wide";
  /** Open over another dialog (the signing step-up opens over an escalation's decision). */
  above?: boolean;
  testId?: string;
  children: ReactNode;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panel.current?.focus();   // the panel itself: the title is read first, and no button is one key press from firing
    return () => { if (before?.isConnected) before.focus(); };
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

  return (
    <div className={`dialog-backdrop${above ? " step-up" : ""}`} data-testid={testId} onKeyDown={onKeyDown}>
      <div ref={panel} className={`dialog${size ? ` ${size}` : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <h2 id={titleId} className="dialog-title">{title}</h2>
        {children}
      </div>
    </div>
  );
}
