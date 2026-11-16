// What a new answer makes of the page's other answers (final review round 5): which of two answers of the same read is
// the newer when a decision's answer meets a read still on its way, which cards a new answer of the delivery page made
// stale, which studies the project's blinding withholds now, and from which moment a change of the blinding is followed
// (round 6). Pure functions on what the API answered, so they are
// checked without a browser (e2e/inputs-work.spec.ts); `lib/hooks.ts`, `components/delivery/writes.ts` and the Inputs
// workspace apply them.

import type { Schema } from "./api";

/** A read of an answer still on its way: when it was asked for (its query started) and when its request went out (null:
 *  it waits its turn behind the page's other reads and has not gone out yet). Times are one clock's (`performance`). */
export type ReadOnItsWay = { asked: number; sent: number | null };

/** What to do with a read of the same answer still on its way when a decision's answer is written (`put`):
 *  - "none": no read is on its way;
 *  - "cancel": it was asked for before the decision was sent, for something that had happened by then, which the
 *    decision's answer (put together after the decision) holds: called off, so it cannot put back what was before;
 *  - "keep": it was asked for since, and has not gone out: it goes out after the answer arrived and reads what the
 *    decision did, so it is left to land;
 *  - "again": it went out after the decision was sent, so the server may have answered it before the decision or after
 *    (or the decision's time is not known): neither answer can be called the newer, so it is called off and the answer
 *    read once more, after both (round 4's rule called every such read off, and a newer read could be lost to an older
 *    answer).
 *  `decided`: when the decision was sent (null: not known). */
export function afterAnswer(read: ReadOnItsWay | null, decided: number | null): "none" | "cancel" | "keep" | "again" {
  if (read === null) return "none";
  if (decided !== null && read.asked < decided) return "cancel";
  return read.sent === null ? "keep" : "again";
}

type Row = Schema<"DeliverySubjectRow">;
type Page = { subjects: Row[] };

/** A subject's reference as the cards are keyed: `${type}/${subject}`. */
export const subjectRef = (s: { subject_type: string; subject: string }) => `${s.subject_type}/${s.subject}`;

/** What a new answer of the delivery page changed of its subjects' rows, against the answer before it (none: the page was
 *  not read before, and no card was drawn from it): `changed`, the subjects whose row is new or differs in anything a card
 *  shows too (its values and how they were read, its files, arms and batches, its confirmation, what of the same source
 *  is in the model, where it is confirmed, its name, and whether and why it is blinded), as `${type}/${subject}`;
 *  `blinding`, whether a subject's blinding changed (it was blinded or no longer is, or for another reason), which also
 *  changes what the client's files, the sheet form and the documents withhold. */
export function changedRows(before: Page | undefined, after: Page): { changed: string[]; blinding: boolean } {
  if (!before) return { changed: [], blinding: false };
  const was = new Map(before.subjects.map((s) => [subjectRef(s), s] as const));
  const changed: string[] = [];
  let blinding = false;
  for (const row of after.subjects) {
    const old = was.get(subjectRef(row));
    if (old && JSON.stringify(old) === JSON.stringify(row)) continue;
    changed.push(subjectRef(row));
    if ((old?.blinded ?? false) !== row.blinded || (old?.blinded_why ?? null) !== (row.blinded_why ?? null)) blinding = true;
  }
  return { changed, blinding };
}

/** The studies the project's blinding list withholds now, as the inputs name them (`InputsPage.studies[].blinded`), in
 *  one string: when it changes, what the list withholds elsewhere changed too (the client's files and sheets, the sheet
 *  form's groups, the evidence's datasets, the delivery's studies and the products that hold their values). Null before
 *  the inputs are read. */
export function blindedStudies(inputs: { studies: { study_id: string; blinded: boolean }[] } | null | undefined): string | null {
  if (!inputs) return null;
  return [...new Set(inputs.studies.filter((s) => s.blinded).map((s) => s.study_id))].sort().join("|");
}

/** A following of a change of the project's blinding: the moment it followed from, and the moment its reads were sent in. */
export type Followed = { since: number; at: number };

/** The moment a change of the project's blinding is followed from (final review round 6, `followBlinding`): `since`, the
 *  moment the answer that shows it was read in (what was read or written in that moment or later holds the change); or,
 *  when that answer was read by the last following (`last`: read between the moment it followed from and the moment its
 *  reads were sent in), the last following's: the answer shows the change that following read everything again for, so
 *  what it read is not read twice (round 5's gap a). An answer read before or after it is followed from its own. */
export function followFrom(last: Followed | undefined, since: number): number {
  return last && since >= last.since && since <= last.at ? last.since : since;
}
