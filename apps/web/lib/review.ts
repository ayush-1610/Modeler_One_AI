// Step 3 · Review & sign (docs/plans/2026-10-19-p0-p5-redesign.md §3.3): the review table and credibility, read from
// `GET /projects/{id}/plan/review`. An input or a study is excluded through the Inputs routes, with a reason; the plan
// itself is changed on the canvas (lib/plan.ts).

import { send, type Schema } from "./api";

export type ReviewPage = Schema<"ReviewPage">;
export type ReviewRow = Schema<"ReviewRow">;
export type ReviewStudy = Schema<"ReviewStudy">;

export type Filter = "all" | "flagged" | "by_person" | "from_agent" | "open";

export const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" }, { id: "flagged", label: "Flagged" }, { id: "by_person", label: "Changed by a person" },
  { id: "from_agent", label: "From an agent" }, { id: "open", label: "Waiting on you" },
];

export function matches(row: ReviewRow, filter: Filter): boolean {
  if (filter === "flagged") return row.flags.length > 0 || row.state === "held" || row.state === "conflict";
  if (filter === "by_person") return row.changed_by_person;
  if (filter === "from_agent") return row.supplied_by === "agent";
  if (filter === "open") return row.state !== "kept";
  return true;
}

export const STATE_LABEL: Record<ReviewRow["state"], { label: string; chip: string }> = {
  kept: { label: "in the model", chip: "low" }, conflict: { label: "keep one", chip: "high" },
  held: { label: "check it", chip: "medium" }, missing: { label: "missing", chip: "high" },
};

export const CONFIDENCE_CHIP: Record<NonNullable<ReviewRow["confidence"]>, string> = {
  high: "low", medium: "medium", low: "high",
};

const project = (projectId: string) => ({ project_id: projectId });

export const reviewApi = {
  /** Set an input's kept source aside: the next source takes its place, or the input waits for a value (Inputs). */
  exclude: (projectId: string, evidenceId: string, reason: string) =>
    send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:decide", { project_id: projectId, evidence_id: evidenceId },
         { state: "REJECTED", reason }),
  /** Leave a study out of the model, or take it back (`reason` is why it was left out; null includes it again). */
  leaveOut: (projectId: string, studyId: string, why: string | null, reason: string) =>
    send("put", "/api/v1/projects/{project_id}/inputs/choices", project(projectId),
         { kind: "excluded_studies", key: studyId, value: why, reason }),
};

/** Seconds as the review shows a stage's share: "34 min", "1 h 36 min". */
export function minutes(seconds: number): string {
  const total = Math.round(seconds / 60);
  const h = Math.floor(total / 60);
  return h ? `${h} h${total % 60 ? ` ${total % 60} min` : ""}` : `${total} min`;
}
