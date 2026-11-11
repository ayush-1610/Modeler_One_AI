// The redesign's small component kit (docs/plans/2026-10-19-p0-p5-redesign.md §7): plain CSS on the theme tokens
// (app/styles/kit.css), no component library. New screens are built from these; old pages keep their own until rebuilt.

// Stepper (a server component) is imported from its own file.

import type { ReactNode, Ref } from "react";

/** A PK-Sim path or parameter id that breaks only after its '.' and '|' separators, never inside a word (the CPF page,
 *  the campaign's influence map on a phone). */
export function breakable(id: string): ReactNode {
  return id.split(/(?<=[.|])/).flatMap((part, i) => (i ? [<wbr key={i} />, part] : [part]));
}

/** Each area's hue for the head's wash and its curve (the "Modeler One App" design, plan 2026-11-06-app-design-merge). */
const HUES = { projects: 211, new: 160, start: 211, inputs: 190, review: 265, run: 150, inbox: 28, library: 280, history: 220, admin: 340 } as const;
export type HeroTone = keyof typeof HUES;

/** A page's head: a pill naming where you are, a large title, one sentence, and the page's actions, centred over a soft
 *  wash of the area's colour and the product's curve (decoration only: it carries no data). */
export function Hero({ eyebrow, title, lede, actions, tone = "projects", size = "compact", testId }: {
  eyebrow?: ReactNode; title: ReactNode; lede?: ReactNode; actions?: ReactNode; tone?: HeroTone;
  /** "full" for the landing pages (the dashboard, the 404); "compact" for the pages worked on all day, so the work
   *  starts within the first screen (the 2026-11-11 audit, item 5). */
  size?: "full" | "compact";
  testId?: string;
}) {
  return (
    <header className={`hero-band ${size}`} style={{ ["--hue" as string]: HUES[tone] }} data-testid={testId}>
      <svg className="hero-art" aria-hidden viewBox="0 0 1440 360" preserveAspectRatio="xMidYMid slice">
        <path className="grid" d="M0 90H1440M0 180H1440M0 270H1440" />
        <path className="curve" d="M0 330C260 330 300 70 560 70s320 230 880 255" pathLength={520} />
        <path className="curve2" d="M0 330C260 330 310 105 570 105s330 190 870 215" />
        <g className="dots"><circle cx="300" cy="170" r="4" /><circle cx="560" cy="75" r="4" /><circle cx="840" cy="190" r="4" /><circle cx="1180" cy="290" r="4" /></g>
      </svg>
      <div className="hero-inner">
        {eyebrow && <span className="hero-pill">{eyebrow}</span>}
        <h1>{title}</h1>
        {lede && <p className="hero-lede">{lede}</p>}
        {actions && <div className="hero-actions">{actions}</div>}
      </div>
    </header>
  );
}

/** A step's page: its head, the project's steps under it (the Stepper, passed in), and its content beside an optional
 *  side panel. */
export function PageShell({ eyebrow, title, lede, actions, side, steps, tone, children }: {
  eyebrow?: string; title: ReactNode; lede?: ReactNode; actions?: ReactNode; side?: ReactNode; steps?: ReactNode;
  tone?: HeroTone; children: ReactNode;
}) {
  return (
    <div className="shell">
      <Hero eyebrow={eyebrow} title={title} lede={lede} actions={actions} tone={tone} />
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

/** The reason a recorded decision carries (accept, reject, correct, exclude, choose…): a visible label that says it is
 *  kept in the audit trail and is required, so the action's disabled state is never explained by a placeholder alone
 *  (2026-11-11 audit 2, item 7). The placeholder stays as an example of what to write. */
export function ReasonField({ value, onChange, placeholder = "why", ariaLabel, className, inputRef, autoFocus, why, testId,
  label = "Reason, kept in the audit trail" }: {
  value: string; onChange: (v: string) => void; placeholder?: string; ariaLabel?: string; className?: string;
  inputRef?: Ref<HTMLInputElement>; autoFocus?: boolean;
  /** marks the input for "focus the next reason" after a decision (InputsTodo afterThis) */
  why?: string; testId?: string; label?: string;
}) {
  return (
    <label className={`reason-field${className ? ` ${className}` : ""}`}>
      <span className="ctl-label">{label} <span className="req">· required</span></span>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={ariaLabel}
             aria-required ref={inputRef} autoFocus={autoFocus} data-why={why} data-testid={testId} />
    </label>
  );
}

/** A small control with its name (and unit) shown above it, so a filled-in field can still be told apart from its
 *  neighbours. `required` adds the same "· required" mark as ReasonField. */
export function LabeledControl({ label, required, className, children }: {
  label: ReactNode; required?: boolean; className?: string; children: ReactNode;
}) {
  return (
    <label className={`ctl-field${className ? ` ${className}` : ""}`}>
      <span className="ctl-label">{label}{required && <span className="req"> · required</span>}</span>
      {children}
    </label>
  );
}

/** What a disabled action still waits for, said beside it (never only in a title tooltip). */
export function WaitingFor({ children, testId }: { children: ReactNode; testId?: string }) {
  return <span className="waiting-for" data-testid={testId}>{children}</span>;
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
