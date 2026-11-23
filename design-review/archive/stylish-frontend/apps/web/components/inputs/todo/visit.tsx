"use client";

// What To do keeps for the length of a visit, above its groups (final review CODE-3, A11Y-2 and the owner-job e2e's gaps
// 2 and 5): a batch table leaves the page with its last row, so what outlives the rows lives here. The layout dialog
// (the queue of layouts to check, or one layout opened from a table's row) stays open until the person closes it, even
// when its decision settles the last row and its group goes; and what was marked as not data in this visit stays listed
// with "Restore…" and a line saying what was done, even when no loose number is left.

import { createContext, useContext } from "react";

import type { MappingAt } from "@/components/delivery/MappingReview";
import type { FileRow } from "@/components/delivery/shared";

/** Loose numbers marked as not data in this visit: the file, the notes' places, how they are named, and the To do group
 *  whose table marked them (`notread` or `tidy`), where they are listed while that table is shown. */
export type Marked = { id: string; file: FileRow; items: string[]; label: string; group: string };
/** A layout the dialog shows: its id, its version (none: its latest) and the table it is shown on. */
export type LayoutAt = { id: string; version?: number; at?: MappingAt };
/** The layout dialog: the layouts it walks (a queue: Previous, Next, "Approve and next"; or one layout), where it is, and
 *  the heading the focus goes to when it closes on a row its decision settled. */
export type LayoutWalk = { list: LayoutAt[]; at: number; queue: boolean; heading: string };

export type TodoVisit = {
  marked: Marked[];
  /** what the last "Mark as not data" did, said where the marked notes are listed (not only to a screen reader) */
  said: string | null;
  mark: (entries: Omit<Marked, "id">[], said: string) => void;
  /** a marked entry restored: no longer listed, and what the restore did said in place of the last mark (round 2's
   *  gate-todo skeptic: the line kept saying the restored numbers were marked) */
  unmark: (id: string, said: string) => void;
  /** open the layout dialog */
  walk: (walk: LayoutWalk) => void;
};

export const TodoVisitContext = createContext<TodoVisit | null>(null);

/** To do's visit state; the batch tables are only ever shown inside To do, which provides it. */
export function useTodoVisit(): TodoVisit {
  const visit = useContext(TodoVisitContext);
  if (!visit) throw new Error("a batch table is shown inside To do (TodoVisitContext)");
  return visit;
}
