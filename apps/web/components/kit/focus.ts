// Where the focus goes after a decision in a list (plan 2026-11-14 slice 4; the design text's "After each decision"): to
// the first control of the next row still there, else to the list's heading (tabIndex -1), else to the fallback. The rows
// are found by their test ids; the decided rows leave the list once the answer is drawn, so the focus is moved once they
// are gone (a few frames at most). The same rule for a control that removes itself (a Cancel, a bar's Clear, a question
// answered): it hands the focus to what opened it or to the next control there (`focusSoon`, final review A11Y-5).

const CONTROLS = "input:not([disabled]), select:not([disabled]), button:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])";

const byTestId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${CSS.escape(id)}"]`);

/** The row to move to after `decided` (test ids of rows, in `rows`' order): the next one after the last decided, else the
 *  one before; none when every row was decided. */
export function nextRow(rows: string[], decided: string[]): string | null {
  const at = Math.max(-1, ...decided.map((d) => rows.indexOf(d)));
  return [...rows.slice(at + 1), ...rows.slice(0, Math.max(0, at)).reverse()].find((r) => !decided.includes(r)) ?? null;
}

/** Move the focus once the decided rows are drawn out of the list: to `next`'s first control, or to the first of the
 *  `headings` (element ids) still on the page. */
export function focusAfter(decided: string[], next: string | null, headings: string[]) {
  let frames = 0;
  const go = () => {
    if (decided.some((d) => byTestId(d)) && frames++ < 20) { window.requestAnimationFrame(go); return; }
    const row = next ? byTestId(next) : null;
    const target = row?.querySelector<HTMLElement>(CONTROLS) ?? row
      ?? headings.map((h) => document.getElementById(h)).find((el): el is HTMLElement => Boolean(el));
    target?.focus();
  };
  window.requestAnimationFrame(go);
}

/** The element a target names, as something that takes the focus: the element itself when it can, else its first
 *  control, else the element when it is focusable by script (a heading with tabIndex -1). */
function focusable(el: HTMLElement): HTMLElement | null {
  if (el.matches(CONTROLS)) return el;
  return el.querySelector<HTMLElement>(CONTROLS) ?? (el.hasAttribute("tabindex") ? el : null);
}

/** Hand the focus on when the control that had it goes away (final review A11Y-5: a form closed with Cancel, a bar
 *  cleared, a question answered): to the first of `targets` (test ids, else element ids) drawn and able to take it, once
 *  the change is drawn (a few frames at most). Never left on the page's body. */
export function focusSoon(...targets: (string | null | undefined)[]) {
  let frames = 0;
  const go = () => {
    for (const t of targets) {
      const el = t ? byTestId(t) ?? document.getElementById(t) : null;
      const to = el ? focusable(el) : null;
      if (!to) continue;
      to.focus();
      if (document.activeElement === to) return;
    }
    if (frames++ < 20) window.requestAnimationFrame(go);
  };
  window.requestAnimationFrame(go);
}
