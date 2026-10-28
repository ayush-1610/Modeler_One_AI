// The Start screen (redesign §3.1): the short brief, the ICH M15 model risk, the scope gates and the data checklist,
// all read from `GET /projects/{id}/brief` and changed through `PUT` on it, with no reason asked (D-27).

import type { Body, Schema } from "./api";
import { EMPTY_RECORD, type BriefView, type Citation, type FieldDef, type FieldRecord, type Question } from "./brief";

export type Gate = Schema<"ScopeGateView">;
export type BriefChange = Body<"/api/v1/projects/{project_id}/brief", "put">["changes"][number];
/** Saves the changes in one version of the brief; answers the API's reason when it refused them. */
export type Save = (changes: BriefChange[]) => Promise<string | null>;
/** Shows a citation's quote, highlighted on its page, in the document viewer. */
export type Open = (citation: Citation) => void;

const GROUP_PATH = /^([a-z_]+)\[(\d+)\]\.([a-z0-9_]+)$/;

/** The definition of a field (`qoi.text`) or of a group item's field (`scenarios[0].route`). */
export function defOf(view: BriefView, path: string): FieldDef {
  const match = GROUP_PATH.exec(path);
  const def = match
    ? view.catalog.groups.find((g) => g.id === match[1])?.fields.find((f) => f.id === match[3])
    : view.catalog.fields.find((f) => f.id === path);
  if (!def) throw new Error(`the brief has no field ${path}`);
  return def;
}

export function recordOf(view: BriefView, path: string): FieldRecord {
  const match = GROUP_PATH.exec(path);
  if (!match) return view.brief.fields[path] ?? EMPTY_RECORD;
  return view.brief.groups[match[1]]?.[Number(match[2])]?.[match[3]] ?? EMPTY_RECORD;
}

/** A field's value when it holds one a person or a source stated (MISSING and NOT_APPLICABLE hold none). */
export function valueOf(view: BriefView, path: string): unknown {
  const record = recordOf(view, path);
  return record.status === "MISSING" || record.status === "NOT_APPLICABLE" ? null : record.value;
}

export const GATE_STATE: Record<Gate["state"], { label: string; tone: string }> = {
  supported: { label: "supported", tone: "low" },
  limited: { label: "limited", tone: "medium" },
  not_supported: { label: "not supported yet", tone: "high" },
  not_set: { label: "not set", tone: "neutral" },
};

export type Answer = (questionId: string, text: string, status: "answered" | "accepted_as_limitation") => void;
export type StartIssue = Schema<"StartIssueView">;
export type Application = Schema<"ApplicationView">;

/** What Start still needs, marked on the field it belongs to (page review 1: no side panel; each box that waits on the
 *  person is marked in red). A group item's issue (`scenarios[0].route`) is also the group's (`scenarios`). */
export type Marks = {
  issues: (path: string) => string[];
  questions: (path: string) => Question[];
  answer: Answer;
};

const QUESTION_PREFIX = "Open question on ";

export function marks(view: BriefView, answer: Answer): Marks {
  const byPath = new Map<string, string[]>();
  for (const issue of view.start.issues) {
    if (issue.message.startsWith(QUESTION_PREFIX)) continue;  // shown with its answer, below
    const group = issue.path.split("[")[0];
    for (const key of new Set([issue.path, group])) byPath.set(key, [...(byPath.get(key) ?? []), issue.message]);
  }
  return {
    issues: (path) => byPath.get(path) ?? [],
    questions: (path) => view.brief.questions.filter((q) => q.status === "open" && q.field === path),
    answer,
  };
}
