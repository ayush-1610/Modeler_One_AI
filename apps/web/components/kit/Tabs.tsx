"use client";

// The kit's tabs (redesign plan §7): a tablist with the keys a keyboard user expects (arrows, Home and End move and select;
// only the selected tab is in the Tab order) and a panel each tab names. The caller keeps rendering only the selected
// panel's content, so what is not shown is not in the page. The look is the shared `.tabs` rule; `className` adds a
// page's own (the Inputs area bar, plan 2026-11-14 slice 1). In a row that scrolls sideways (that bar on a phone) the
// selected tab is kept in view however it was chosen: a tap, a key, a link (?tab=) or the page itself.

import { type KeyboardEvent, type ReactNode, useEffect, useRef } from "react";

export type TabItem<T extends string> = {
  id: T; label: string;
  /** A number beside the label, e.g. the open items on that tab; read aloud with `countLabel` ("N open"). */
  count?: number;
  /** What the count counts, read aloud after it: "open" unless said ("to do", "files"). */
  countLabel?: string;
  /** A chip after the count (the Client files tab's "2 to place"). */
  badge?: ReactNode;
  testId?: string;
};

const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`;

export function Tabs<T extends string>({ label, prefix, tabs, value, onChange, className }: {
  label: string; prefix: string; tabs: TabItem<T>[]; value: T; onChange: (id: T) => void; className?: string;
}) {
  const list = useRef<HTMLDivElement>(null);
  // only the row scrolls, never the page: the selected tab is brought just inside the row's edge it lies beyond, again
  // when the counts arrive and widen the tabs before it
  const widths = tabs.map((t) => `${t.label}:${t.count ?? ""}:${t.badge ? 1 : 0}`).join("|");
  useEffect(() => {
    const row = list.current;
    const tab = row?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
    if (!row || !tab || row.scrollWidth <= row.clientWidth) return;
    const edge = row.getBoundingClientRect(), box = tab.getBoundingClientRect();
    if (box.left < edge.left) row.scrollLeft -= edge.left - box.left + 8;
    else if (box.right > edge.right) row.scrollLeft += box.right - edge.right + 8;
  }, [value, widths]);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const at = tabs.findIndex((t) => t.id === value);
    const to = e.key === "ArrowRight" ? (at + 1) % tabs.length : e.key === "ArrowLeft" ? (at - 1 + tabs.length) % tabs.length
      : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    onChange(tabs[to].id);
    document.getElementById(tabId(prefix, tabs[to].id))?.focus();
  };
  return (
    <div ref={list} className={className ? `tabs ${className}` : "tabs"} role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((t) => (
        <button key={t.id} type="button" role="tab" id={tabId(prefix, t.id)} aria-selected={value === t.id}
                aria-controls={panelId(prefix, t.id)} tabIndex={value === t.id ? 0 : -1}
                className={value === t.id ? "active" : ""} onClick={() => onChange(t.id)} data-testid={t.testId}>
          {t.label}
          {!!t.count && <span className="tab-count">{t.count}<span className="sr-only"> {t.countLabel ?? "open"}</span></span>}
          {t.badge}
        </button>
      ))}
    </div>
  );
}

/** The selected tab's content. */
export function TabPanel({ prefix, id, children }: { prefix: string; id: string; children: ReactNode }) {
  return (
    <div className="tabpanel" role="tabpanel" id={panelId(prefix, id)} aria-labelledby={tabId(prefix, id)}>
      {children}
    </div>
  );
}
