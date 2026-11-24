// The redesign's small component kit (docs/plans/2026-10-19-p0-p5-redesign.md §7): plain CSS on the theme tokens
// (app/styles/kit.css), no component library. New screens are built from these; old pages keep their own until rebuilt.

// Stepper (a server component) is imported from its own file.

import { Fragment, type ReactNode } from "react";

import { Breadcrumbs } from "@/components/shell/Breadcrumbs";

/** The area a page belongs to. Kept for the callers that name it; the console's header draws no colour wash (decision
 *  G1-2: no decorative headers). */
export type HeroTone = "projects" | "new" | "start" | "inputs" | "review" | "run" | "inbox" | "library" | "history" | "admin";

/** A page's header (design-review/DESIGN_SYSTEM.md §5.1): breadcrumbs, the title, one sentence, and the page's actions on
 *  the right. Compact (about 88 px) so the work starts on the first screen; it replaces the 300-420 px hero of the
 *  7 Nov look. `eyebrow`, `tone` and `size` are accepted and ignored: the breadcrumbs say where the page is. */
export function Hero({ title, lede, actions, testId }: {
  eyebrow?: ReactNode; title: ReactNode; lede?: ReactNode; actions?: ReactNode; tone?: HeroTone;
  size?: "full" | "compact" | "slim";
  testId?: string;
}) {
  return (
    <header className="page-head" data-testid={testId}>
      <Breadcrumbs />
      <div className="page-head-row">
        <div className="page-head-titles">
          <h1>{title}</h1>
          {lede && <p className="hero-lede page-desc">{lede}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
    </header>
  );
}

/** A step's page: its head, the project's steps under it (the Stepper, passed in), and its content beside an optional
 *  side panel. `noReveal` is accepted and ignored: nothing fades in
 *  any more (the motion system is gone, decision G1-2). `slim` (opt-in): a shorter head and less
 *  space under it, so a page's own bar sits high (Inputs, plan 2026-11-14 slice 2); other pages keep theirs. `before`:
 *  what comes first in the page's Tab order, before its head (a page's own skip link). */
export function PageShell({ eyebrow, title, lede, actions, side, steps, tone, slim, before, children }: {
  eyebrow?: string; title: ReactNode; lede?: ReactNode; actions?: ReactNode; side?: ReactNode; steps?: ReactNode;
  tone?: HeroTone; noReveal?: boolean; slim?: boolean; before?: ReactNode; children: ReactNode;
}) {
  return (
    <div className={slim ? "shell slim" : "shell"}>
      {before}
      <Hero eyebrow={eyebrow} title={title} lede={lede} actions={actions} tone={tone} size={slim ? "slim" : "compact"} />
      {steps}
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
 *  caption (read aloud, not drawn) and its scrolling box can be reached and scrolled from the keyboard. `rowTestId`
 *  names each row; `after` draws what a row opens on, in a full-width row under it (a study's card under its row). */
export function DataTable<T>({ columns, rows, rowKey, empty, testId, label, rowTestId, rowClassName, after, className, group }: {
  columns: Column<T>[]; rows: T[]; rowKey: (row: T) => string; empty?: ReactNode; testId?: string; label?: string;
  rowTestId?: (row: T) => string; rowClassName?: (row: T) => string | undefined; after?: (row: T) => ReactNode; className?: string;
  /** rows in groups (in the order given): a heading row before each group's first row; a row that moves to another group
   *  stays the same row, so what it opened stays open */
  group?: { of: (row: T) => string; title: (group: string, rows: T[]) => ReactNode; testId?: (group: string) => string };
}) {
  if (!rows.length) return <>{empty ?? <EmptyState title="Nothing here yet" />}</>;
  return (
    <div className="table-scroll" data-testid={testId} {...(label ? { role: "region", "aria-label": label, tabIndex: 0 } : {})}>
      <table className={className}>
        {label && <caption className="sr-only">{label}</caption>}
        <thead><tr>{columns.map((c) => <th key={c.key} className={c.numeric ? "num" : undefined}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => {
            const more = after?.(r);
            const g = group?.of(r);
            const heading = group && g !== undefined && (i === 0 || group.of(rows[i - 1]) !== g);
            return (
              <Fragment key={rowKey(r)}>
                {heading && (
                  <tr className="row-group" data-testid={group.testId?.(g)}>
                    <th colSpan={columns.length} scope="colgroup">{group.title(g, rows.filter((x) => group.of(x) === g))}</th>
                  </tr>
                )}
                <tr data-testid={rowTestId?.(r)} className={rowClassName?.(r)}>
                  {columns.map((c) => <td key={c.key} className={c.numeric ? "num" : undefined}>{c.render(r)}</td>)}
                </tr>
                {more && <tr className="row-detail"><td colSpan={columns.length}>{more}</td></tr>}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
