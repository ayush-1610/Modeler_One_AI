"use client";

// The kit's tabs (redesign plan §7): a tablist with the keys a keyboard user expects (arrows, Home and End move and select;
// only the selected tab is in the Tab order) and a panel each tab names. The caller keeps rendering only the selected
// panel's content, so what is not shown is not in the page. The look is the shared `.tabs` rule.

import type { KeyboardEvent, ReactNode } from "react";

export type TabItem<T extends string> = {
  id: T; label: string;
  /** A number beside the label, e.g. the open items on that tab; read aloud as "N open". */
  count?: number;
  testId?: string;
};

const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`;

export function Tabs<T extends string>({ label, prefix, tabs, value, onChange }: {
  label: string; prefix: string; tabs: TabItem<T>[]; value: T; onChange: (id: T) => void;
}) {
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
    <div className="tabs" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((t) => (
        <button key={t.id} type="button" role="tab" id={tabId(prefix, t.id)} aria-selected={value === t.id}
                aria-controls={panelId(prefix, t.id)} tabIndex={value === t.id ? 0 : -1}
                className={value === t.id ? "active" : ""} onClick={() => onChange(t.id)} data-testid={t.testId}>
          {t.label}
          {!!t.count && <span className="tab-count">{t.count}<span className="sr-only"> open</span></span>}
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
