// The redesign's small component kit (docs/plans/2026-10-19-p0-p5-redesign.md §7): plain CSS on the theme tokens
// (app/styles/kit.css), no component library. New screens are built from these; old pages keep their own until rebuilt.

// Stepper (a server component) and ThemeToggle (a client one) are imported from their own files.

import type { ReactNode } from "react";

/** A step's page: what it is for, the actions it offers, and its content beside an optional side panel. */
export function PageShell({ eyebrow, title, lede, actions, side, children }: {
  eyebrow?: string; title: ReactNode; lede?: ReactNode; actions?: ReactNode; side?: ReactNode; children: ReactNode;
}) {
  return (
    <div className="shell">
      <header className="shell-head">
        <div className="shell-title">
          {eyebrow && <span className="eyebrow">{eyebrow}</span>}
          <h1>{title}</h1>
          {lede && <p className="lede">{lede}</p>}
        </div>
        {actions && <div className="shell-actions">{actions}</div>}
      </header>
      <div className={side ? "shell-body with-side" : "shell-body"}>
        <div className="shell-main">{children}</div>
        {side && <aside className="shell-side">{side}</aside>}
      </div>
    </div>
  );
}

/** A box of the side panel: a short heading and what it says. */
export function SidePanel({ title, tone, children, testId }: {
  title: string; tone?: "warn" | "ok"; children: ReactNode; testId?: string;
}) {
  return (
    <section className={`side-panel${tone ? ` ${tone}` : ""}`} data-testid={testId}>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

/** What the page shows when there is nothing yet: what will appear, and how to add the first one. */
export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

/** A problem shown next to the thing it is about: a blocker ("error"), a caution ("warn") or a note. */
export function InlineIssue({ severity = "warn", children, testId }: {
  severity?: "error" | "warn" | "note"; children: ReactNode; testId?: string;
}) {
  return <p className={`inline-issue ${severity}`} role={severity === "error" ? "alert" : undefined} data-testid={testId}>{children}</p>;
}

/** A result or a refusal the person should hear about: a note for what went fine or a caution, an alert for a refusal. */
export function Banner({ tone, children, testId }: { tone: "ok" | "warn" | "err"; children: ReactNode; testId?: string }) {
  return <div className={`banner ${tone}`} role={tone === "err" ? "alert" : "status"} data-testid={testId}>{children}</div>;
}

export type Column<T> = { key: string; label: string; numeric?: boolean; render: (row: T) => ReactNode };

/** A table that scrolls inside its own box on a narrow screen and says when it is empty. With a `label` the table has a
 *  caption (read aloud, not drawn) and its scrolling box can be reached and scrolled from the keyboard. */
export function DataTable<T>({ columns, rows, rowKey, empty, testId, label }: {
  columns: Column<T>[]; rows: T[]; rowKey: (row: T) => string; empty?: ReactNode; testId?: string; label?: string;
}) {
  if (!rows.length) return <>{empty ?? <EmptyState title="Nothing here yet" />}</>;
  return (
    <div className="table-scroll" data-testid={testId} {...(label ? { role: "region", "aria-label": label, tabIndex: 0 } : {})}>
      <table>
        {label && <caption className="sr-only">{label}</caption>}
        <thead><tr>{columns.map((c) => <th key={c.key} className={c.numeric ? "num" : undefined}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={rowKey(r)}>{columns.map((c) => <td key={c.key} className={c.numeric ? "num" : undefined}>{c.render(r)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
