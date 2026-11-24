"use client";

// The console's table (design-review/DESIGN_SYSTEM.md §5.4, the redesign's slice 2): a panel with a header (title, count,
// actions), an optional text filter and tools, sortable columns, and an empty state in words. Sorting starts in the
// order the rows arrive, until a column is pressed (the 2026-11-11 audit, item 11). Not paged: a row just made is never
// on a later page.

import { useMemo, useState, type ReactNode } from "react";

export type Column<T> = {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  /** The value a press on the header sorts by; a column without one is not sortable. */
  sort?: (row: T) => string | number;
  num?: boolean;
};

export function Table<T>({ title, count, actions, columns, rows, rowKey, rowTestId, filter, tools, empty, testId, caption }: {
  title?: ReactNode;
  /** Shown after the title, e.g. "(12)"; defaults to the number of rows. */
  count?: number | null;
  actions?: ReactNode;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  rowTestId?: (row: T) => string;
  /** A text filter over each row's words. */
  filter?: { placeholder: string; text: (row: T) => string; testId?: string };
  tools?: ReactNode;
  empty: ReactNode;
  testId?: string;
  /** The table's accessible name when it has no title. */
  caption?: string;
}) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const kept = filter && needle ? rows.filter((r) => filter.text(r).toLowerCase().includes(needle)) : rows;
    const col = sort && columns.find((c) => c.key === sort.key);
    if (!col?.sort) return kept;
    const by = col.sort;
    return [...kept].sort((a, b) => {
      const x = by(a), y = by(b);
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * sort!.dir;
    });
  }, [rows, q, sort, columns, filter]);
  const press = (key: string) => setSort((s) => (s?.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: 1 }));
  const n = count === undefined ? rows.length : count;
  return (
    <section className="tbl" data-testid={testId} aria-label={title ? undefined : caption}>
      {(title || actions) && (
        <div className="tbl-head">
          {title && <h2>{title}{n !== null && <span className="tbl-count"> ({n})</span>}</h2>}
          <span className="grow" />
          {actions}
        </div>
      )}
      {(filter || tools) && (
        <div className="tbl-tools">
          {filter && (
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={filter.placeholder}
                   aria-label={filter.placeholder} data-testid={filter.testId} />
          )}
          {tools}
        </div>
      )}
      {rows.length === 0 ? <div className="tbl-empty">{empty}</div>
        : shown.length === 0 ? (
          <div className="tbl-empty">No row matches. <button type="button" className="link-btn" onClick={() => setQ("")}>Clear the filter</button></div>
        ) : (
          <div className="tbl-scroll">
            <table>
              {!title && caption && <caption className="sr-only">{caption}</caption>}
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c.key} scope="col" className={c.num ? "num" : undefined}
                        aria-sort={sort?.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}>
                      {c.sort ? (
                        <button type="button" className="tbl-sort" onClick={() => press(c.key)}>
                          {c.label}<span aria-hidden className="tbl-arrow">{sort?.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : "↕"}</span>
                        </button>
                      ) : c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={rowKey(r)} data-testid={rowTestId?.(r)}>
                    {columns.map((c) => <td key={c.key} className={c.num ? "num" : undefined}>{c.render(r)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </section>
  );
}

/** A project's four steps as four small bars, each with its state in the accessible name. */
export function StepsMini({ steps }: { steps: { step: string; label: string; state: string }[] | null | undefined }) {
  if (!steps || steps.length === 0) return <span className="muted">Steps not read</span>;
  const word: Record<string, string> = { done: "done", needs_you: "needs you", running: "running", not_started: "not started" };
  // the steps as the side navigation names them (step 2 is Data: the Data room and Inputs, decision G1-1)
  const name: Record<string, string> = { start: "Start", inputs: "Data", review: "Review & sign", run: "Run" };
  return (
    <span className="steps-mini" role="img" aria-label={steps.map((s) => `${name[s.step] ?? s.label}: ${word[s.state] ?? s.state}`).join(", ")}>
      {steps.map((s) => <i key={s.step} className={s.state} />)}
    </span>
  );
}
