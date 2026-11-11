"use client";

// Sorting, filtering and paging for a long table (the 2026-11-11 audit, item 11). The default order is the order the
// rows arrive in (the API's), so nothing reshuffles until a header is pressed. A row that needs the person's action
// (`keep`: a blinded study, a missing regimen, an overlay to check, an open conflict) is never hidden by paging or by a
// filter: it is always shown, and the table says how many need attention. The pure helpers are in lib/tableSort.ts.

import { useCallback, useEffect, useMemo, useState } from "react";

import { compareKeys, type SortKey } from "./tableSort";

export { compareKeys, numericKey, ordinal, type SortDir, type SortKey, type SortState } from "./tableSort";
import type { SortState } from "./tableSort";

export type TableView<T> = {
  visible: T[];
  /** every row; the rows that pass the filter; the rows that need attention (always shown) */
  total: number; matched: number; attention: number;
  /** rows that pass the filter but are not shown yet */
  remaining: number;
  sort: SortState; toggle: (col: string) => void; setSort: (s: SortState) => void;
  ariaSort: (col: string) => "ascending" | "descending" | "none";
  query: string; setQuery: (q: string) => void;
  more: () => void; all: () => void; pageSize: number | null;
};

export function useTableView<T>({ rows, keys, text, filter, filterKey = "", keep, pageSize = null, tail = false, initialSort = null }: {
  rows: T[];
  /** the sort key of each sortable column */
  keys: Record<string, (r: T) => SortKey>;
  /** the words the text filter searches */
  text?: (r: T) => string;
  /** a narrower filter (chips); `filterKey` names its state, so the first page comes back when it changes */
  filter?: (r: T) => boolean; filterKey?: string;
  /** rows always shown, whatever the page or filter */
  keep?: (r: T) => boolean;
  /** rows shown before "Show more"; null shows them all */
  pageSize?: number | null;
  /** page from the end (the newest rows of a chronological table) */
  tail?: boolean;
  initialSort?: SortState;
}): TableView<T> {
  const [sort, setSort] = useState<SortState>(initialSort);
  const [query, setQueryState] = useState("");
  const [limit, setLimit] = useState<number | null>(pageSize);
  useEffect(() => { setLimit(pageSize); }, [filterKey, pageSize]);
  const setQuery = useCallback((q: string) => { setQueryState(q); setLimit(pageSize); }, [pageSize]);

  const toggle = useCallback((col: string) => setSort((s) =>
    !s || s.col !== col ? { col, dir: "ascending" } : s.dir === "ascending" ? { col, dir: "descending" } : null), []);

  const view = useMemo(() => {
    const key = sort ? keys[sort.col] : undefined;
    const sorted = key
      ? rows.map((r, i) => ({ r, i, k: key(r) })).sort((a, b) => {
          const c = compareKeys(a.k, b.k);
          // nulls stay last in both directions; ties keep the arriving order
          const nulls = a.k === null || a.k === undefined || a.k === "" || b.k === null || b.k === undefined || b.k === "";
          return (c === 0 ? 0 : sort!.dir === "descending" && !nulls ? -c : c) || a.i - b.i;
        }).map((x) => x.r)
      : rows;
    const words = query.trim().toLowerCase();
    const passes = (r: T) => (!filter || filter(r)) && (!words || !text || text(r).toLowerCase().includes(words));
    const passing = sorted.filter(passes);
    const shownSet = new Set<T>(limit === null ? passing : tail ? passing.slice(Math.max(0, passing.length - limit)) : passing.slice(0, limit));
    const kept = keep ? sorted.filter(keep) : [];
    for (const r of kept) shownSet.add(r);
    return {
      visible: sorted.filter((r) => shownSet.has(r)),
      matched: passing.length,
      attention: kept.length,
      remaining: passing.filter((r) => !shownSet.has(r)).length,
    };
  }, [rows, keys, sort, query, text, filter, keep, limit, tail]);

  return {
    ...view, total: rows.length, sort, toggle, setSort, query, setQuery, pageSize,
    ariaSort: (col) => (sort?.col === col ? sort.dir : "none"),
    more: () => setLimit((l) => (l === null || pageSize === null ? null : l + pageSize)),
    all: () => setLimit(null),
  };
}
