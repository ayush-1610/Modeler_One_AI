"use client";

// A long table that sorts by its headers, filters by text and shows its rows a page at a time (the 2026-11-11 audit,
// item 11). Its props can be serialized, so a server page passes cells already rendered and a primitive sort key per
// column (a function cannot cross from a server component to a client one). Client tables with stateful cells use the
// hook (lib/tableView.ts) and the parts below directly. Rows that need action (`keep`) are never paged or filtered out.

import { useRef, useState, type ReactNode } from "react";

import { useTableView, type SortKey, type TableView } from "@/lib/tableView";

/** A sortable column head: a real button inside the th, the order said by aria-sort on the th. */
export function SortHeader<T>({ view, col, label, numeric, className }: {
  view: TableView<T>; col: string; label: ReactNode; numeric?: boolean; className?: string;
}) {
  const state = view.ariaSort(col);
  const next = state === "none" ? "ascending" : state === "ascending" ? "descending" : "the arriving order";
  return (
    <th aria-sort={state} className={[numeric ? "num" : "", className ?? ""].join(" ").trim() || undefined}>
      <button type="button" className="sort-th" onClick={() => view.toggle(col)}
              title={`Sort ${next === "the arriving order" ? "back to the arriving order" : next}`}>
        {label}<span className="sort-ind" aria-hidden />
      </button>
    </th>
  );
}

/** The text filter above a table, with its label for a screen reader. */
export function TableFilter<T>({ view, placeholder, label, testId, children }: {
  view: TableView<T>; placeholder: string; label: string; testId?: string; children?: ReactNode;
}) {
  return (
    <div className="table-tools">
      <input type="search" aria-label={label} placeholder={placeholder} value={view.query} data-testid={testId}
             onChange={(e) => view.setQuery(e.target.value)} />
      {children}
    </div>
  );
}

/** Under the table (outside it, so a row count of the table stays the rows): how many are shown, how many need
 *  attention and are always shown, and "Show N more" / "Show all". Focus stays on a button while it is there; when the
 *  last page is shown and the buttons go, it moves to the count line, which stays (it is rendered whenever there were
 *  more rows to show). */
export function TableMore<T>({ view, noun, testId }: { view: TableView<T>; noun: string; testId?: string }) {
  const here = useRef<HTMLParagraphElement>(null);
  // once there were more rows than shown, the count line stays: the place focus goes when the buttons go
  const [paged, setPaged] = useState(false);
  const filtered = view.matched !== view.total;
  const shown = view.visible.length;
  if (!view.remaining && !filtered && !view.attention && !view.sort && !paged) return null;
  const step = view.pageSize ? Math.min(view.pageSize, view.remaining) : view.remaining;
  // the last page: the button goes, so focus moves to the count line (after the render that removes the button)
  const keepFocus = (fn: () => void, last: boolean) => () => {
    setPaged(true);
    fn();
    if (last) requestAnimationFrame(() => here.current?.focus());
  };
  return (
    <p className="table-more" ref={here} tabIndex={-1} data-testid={testId} aria-live="polite">
      <span>
        {shown} of {view.total} {noun}
        {filtered && ` · ${view.matched} match`}
        {view.attention > 0 && <> · <strong className="table-attention">{view.attention} need{view.attention === 1 ? "s" : ""} attention, always shown</strong></>}
        {view.sort && " · sorted"}
      </span>
      {view.remaining > 0 && (
        <>
          <button type="button" className="btn tiny" onClick={keepFocus(view.more, step >= view.remaining)} data-testid={testId && `${testId}-next`}>
            Show {step} more</button>
          {view.remaining > step && (
            <button type="button" className="btn tiny" onClick={keepFocus(view.all, true)} data-testid={testId && `${testId}-all`}>
              Show all {view.matched}</button>
          )}
        </>
      )}
    </p>
  );
}

export type SortableColumn = { key: string; label: string; numeric?: boolean; sortable?: boolean; className?: string };
export type SortableRow = {
  key: string; cells: ReactNode[]; sort: SortKey[];
  /** the words the text filter searches */
  filter?: string;
  keep?: boolean; testId?: string; id?: string; className?: string;
  /** a cell's own class, in place of its column's (a text value in a numeric column is not right-aligned) */
  cellClassName?: (string | undefined)[];
};

export function SortableTable({ columns, rows, testId, label, noun = "rows", pageSize = null, tail = false, filterPlaceholder, tableClassName }: {
  columns: SortableColumn[]; rows: SortableRow[]; testId?: string; label: string; noun?: string;
  pageSize?: number | null; tail?: boolean; filterPlaceholder?: string; tableClassName?: string;
}) {
  const keys = Object.fromEntries(columns.map((c, i) => [c.key, (r: SortableRow) => r.sort[i]]));
  const view = useTableView({
    rows, keys, pageSize, tail, keep: (r) => Boolean(r.keep), text: filterPlaceholder ? (r) => r.filter ?? "" : undefined,
  });
  return (
    <div className="sortable" data-testid={testId}>
      {filterPlaceholder && <TableFilter view={view} placeholder={filterPlaceholder} label={`Filter ${label.toLowerCase()}`}
                                         testId={testId && `${testId}-filter`} />}
      <div className="table-scroll">
        <table className={tableClassName}>
          <caption className="sr-only">{label}</caption>
          <thead>
            <tr>
              {columns.map((c) => c.sortable === false
                ? <th key={c.key} className={[c.numeric ? "num" : "", c.className ?? ""].join(" ").trim() || undefined}>{c.label}</th>
                : <SortHeader key={c.key} view={view} col={c.key} label={c.label} numeric={c.numeric} className={c.className} />)}
            </tr>
          </thead>
          <tbody>
            {view.visible.map((r) => (
              <tr key={r.key} data-testid={r.testId} id={r.id} className={r.className}>
                {r.cells.map((cell, i) => (
                  <td key={columns[i]?.key ?? i}
                      className={r.cellClassName?.[i] ?? ([columns[i]?.numeric ? "num" : "", columns[i]?.className ?? ""].join(" ").trim() || undefined)}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {view.total === 0 ? <p className="muted table-none">No {noun} yet.</p>
        : view.matched === 0 && view.visible.length === 0 && <p className="muted table-none">No {noun} match “{view.query}”.</p>}
      <TableMore view={view} noun={noun} testId={testId && `${testId}-more`} />
    </div>
  );
}
