"use client";

// Undo "Mark as not data" (plan 2026-11-14 §2.2.4, API 6): a table, a text or a note a person marked as not data is
// given back with the reason, through `regions:restore` with the exclusion's own ids and scope. The decision it undoes
// is said where it is shown: why (the region's reason) and who and when (the project's audit trail, read only while
// such a decision is on screen). The answer is the page, written into the cache: nothing else is read again.

import { send } from "@/lib/api";
import { useResource } from "@/lib/hooks";

import { Problem, Why, personDecision, useDecide, useWritePage, when, type FileRow, type Region } from "./shared";

const RESTORE = "/api/v1/projects/{project_id}/delivery/regions:restore" as const;
// the project's audit events read back for who made a decision: enough for any delivery under review
const AUDIT_EVENTS = "2000";

export type Scope = "regions" | "unread_prose" | "figures" | "outside";
type Who = { by: string; at: string };

/** Who made each person's "not data" decision on screen, and when (`intake.region` events, by the decision's id). Read
 *  only when `wanted`; an empty map until read, or when the trail is not readable. */
export function useDecisionsWho(projectId: string, wanted: boolean): Map<string, Who> {
  const read = useResource("/api/v1/projects/{project_id}/audit", { project_id: projectId }, {
    query: { limit: AUDIT_EVENTS }, enabled: wanted,
    select: (trail) => new Map(trail.events.filter((e) => e.action === "intake.region")
      .map((e) => [e.resource_id.slice(e.resource_id.lastIndexOf("/") + 1), { by: e.actor, at: e.occurred_at }] as const)),
  });
  return read.data ?? new Map();
}

/** A region's "not data" decision in words: by whom, when and why ("Marked as not data by dev-user, 2026-11-14 18:15:
 *  a working note"). Null for a region a rule set aside or one nobody did. */
export function NotDataNote({ region, who, testId }: { region: Region; who: Map<string, Who>; testId?: string }) {
  const decision = region.state === "excluded" ? personDecision(region.reason) : null;
  if (!decision) return null;
  const by = who.get(decision.id);
  return (
    <div className="muted fs-12" data-testid={testId}>
      Marked as not data{by ? ` by ${by.by}, ${when(by.at)}` : ""}: {decision.why}
    </div>
  );
}

/** Whether a person's decision sets this region aside (what "Restore…" can undo); a rule's exclusion cannot be. */
export const restorable = (r: Region) => r.state === "excluded" && personDecision(r.reason) !== null;

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
