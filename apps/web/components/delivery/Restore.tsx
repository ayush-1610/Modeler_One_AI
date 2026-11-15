"use client";

// Undo "Mark as not data" (plan 2026-11-14 §2.2.4, API 6): a table, a text or a note a person marked as not data is
// given back with the reason, through `regions:restore` with the exclusion's own ids and scope. The decision it undoes
// is said where it is shown, as the page gives it (`DeliveryRegion.decision`, `DeliveryOutside.decision`: who, when and
// why, from the decision's own line), and so is the restore that gave a thing back (`restored`), which stays on the
// record. The answer is the page, written into the cache: nothing else is read again.

import { send, type Schema } from "@/lib/api";

import { Problem, Why, useDecide, useWritePage, when, type FileRow, type Region } from "./shared";

const RESTORE = "/api/v1/projects/{project_id}/delivery/regions:restore" as const;

export type Scope = "regions" | "unread_prose" | "figures" | "outside";
type Decision = Schema<"DeliveryRegionDecision">;
type Restored = Schema<"DeliveryRegionRestore">;
type Note = FileRow["outside"][number];

/** A person's "not data" decision in force, in words: "Marked as not data by dev-user, 2026-11-14 18:15: a working
 *  note". With none, the restore that gave the thing back, if any: "Restored by …: why". Null when neither. */
export function DecisionNote({ decision, restored, testId }: { decision: Decision | null; restored?: Restored | null; testId?: string }) {
  if (decision) {
    return <div className="muted fs-12" data-testid={testId}>Marked as not data by {decision.by}, {when(decision.at)}: {decision.why}</div>;
  }
  if (restored) {
    return <div className="muted fs-12" data-testid={testId}>Restored by {restored.by}, {when(restored.at)}: {restored.why}</div>;
  }
  return null;
}

/** A region's "not data" decision (or, with none, its restore) in words; null for a region a rule set aside, or one
 *  nobody decided on. */
export function NotDataNote({ region, testId }: { region: Region; testId?: string }) {
  return <DecisionNote decision={region.decision} restored={region.restored} testId={testId} />;
}

/** Whether a person's decision sets this region aside (what "Restore…" can undo); a rule's exclusion cannot be. */
export const restorable = (r: Region) => r.decision !== null;

/** Whether a person's decision sets this note aside: what "Restore…" can undo. A note that is not counted with no
 *  decision is one a table that is read cites (a fact read once for the table). */
export const restorableNote = (o: Note) => o.decision !== null;

/** The reason form that restores `items` of `file` (region ids, or with scope `outside` the notes' locators). */
export function RestoreForm({ projectId, file, items, scope, label, onDone, testId }: {
  projectId: string; file: FileRow; items: string[]; scope: Scope;
  /** what is restored, read with the field and the button: "the table Sheet1 of 230-23.xlsx" */
  label: string; onDone: () => void; testId: string;
}) {
  const { decide, busy, problem } = useDecide();
  const write = useWritePage(projectId);
  async function restore(why: string) {
    const { data } = await decide(() => send("post", RESTORE, { project_id: projectId },
                                             { file_sha256: file.sha256, regions: items, scope, why }), { refresh: false });
    if (data) { write(data); onDone(); }
  }
  return (
    <>
      <Why action="Restore" actionLabel={`Restore ${label}`} label={`Why ${label} is data after all`} busy={busy} onSubmit={restore}
           onCancel={onDone} testId={testId} autoFocus
           placeholder="why it is data after all (kept on the audit trail)">
        <span className="muted">Restore {label}: what was read from it counts again.</span>
      </Why>
      <Problem text={problem} testId={`${testId}-problem`} />
    </>
  );
}
