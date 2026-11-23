"use client";

// The bar of a batch (plan 2026-11-14 slice 4; the design text's kit `BulkBar`): how many rows are picked, what is done
// with them and the one reason, kept in view at the bottom of its table while the person scrolls it (on a phone too).
// Shown only while something is picked. While it is shown, the page keeps its height clear at the bottom for the focus
// (`--bulk-h`, read by `html:has(.bulk-bar) { scroll-padding-bottom }` in batch.css): a row tabbed to is scrolled above
// the bar, never left under it (final review A11Y-3, WCAG 2.4.11). Cleared, the bar hands the focus to `after` (the
// table's "pick every" box, a row), never to the page (A11Y-5).

import { useEffect, useRef, type ReactNode } from "react";

import { focusSoon } from "./focus";

/** The heights of the bars shown now: the page keeps the tallest clear. */
const HEIGHTS = new Map<object, number>();
function keepClear() {
  const h = Math.max(0, ...HEIGHTS.values());
  if (h) document.documentElement.style.setProperty("--bulk-h", `${Math.ceil(h)}px`);
  else document.documentElement.style.removeProperty("--bulk-h");
}

function Bar({ count, noun, many, onClear, after = [], label, clearLabel, testId, children }: {
  count: number; noun: string; many?: string; onClear: () => void; after?: string[]; label: string; clearLabel?: string; testId?: string;
  children: ReactNode;
}) {
  const bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = bar.current;
    if (!el) return;
    const me = {};
    const measure = () => { HEIGHTS.set(me, el.getBoundingClientRect().height); keepClear(); };
    measure();
    const seen = new ResizeObserver(measure);
    seen.observe(el);
    // and where a browser scrolls only what lies outside the window: a focus that lands under the bar is moved above it
    const clear = (e: FocusEvent) => {
      const at = e.target;
      if (!(at instanceof HTMLElement) || el.contains(at) || at.closest('[role="dialog"]')) return;
      const r = at.getBoundingClientRect(), b = el.getBoundingClientRect();
      if (r.bottom > b.top - 8 && r.top < b.bottom) window.scrollBy({ top: r.bottom - b.top + 16 });
    };
    document.addEventListener("focusin", clear);
    return () => { seen.disconnect(); document.removeEventListener("focusin", clear); HEIGHTS.delete(me); keepClear(); };
  }, []);
  return (
    <div ref={bar} className="bulk-bar" role="region" aria-label={label} data-testid={testId}>
      <div className="bulk-bar-head">
        <strong data-testid={testId && `${testId}-count`}>{count} {count === 1 ? noun : many ?? `${noun}s`} picked</strong>
        <button type="button" className="link-btn" onClick={() => { onClear(); focusSoon(...after); }} data-testid={testId && `${testId}-clear`}
                aria-label={clearLabel ?? `Clear the ${many ?? `${noun}s`} picked`}>Clear</button>
      </div>
      {children}
    </div>
  );
}

export function BulkBar({ count, ...rest }: {
  count: number;
  /** what a row is: "file", "group of loose numbers" */
  noun: string;
  many?: string;
  onClear: () => void;
  /** where the focus goes once the bar is cleared (test ids or element ids, the first drawn): the table's "pick every"
   *  box, the first row picked */
  after?: string[];
  /** the bar's name, read as a region ("Link the picked files") */
  label: string;
  /** "Clear" with what it clears, where two bars can be shown ("Clear the files picked to link") */
  clearLabel?: string;
  testId?: string;
  /** the batch's choices and its reason form */
  children: ReactNode;
}) {
  if (!count) return null;
  return <Bar count={count} {...rest} />;
}
