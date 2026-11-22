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

/** Who drafted a record: the intake agent, or code (from the documents' words, or by the ICH M15 rule, UNVERIFIED). */
export function drafter(record: FieldRecord): string {
  const by = record.by ?? "";
  if (by.startsWith("code:m15")) return "the ICH M15 rule (UNVERIFIED)";
  if (by.startsWith("code:")) return "code";
  return "the intake agent";
}

/** A drafted "no" for nonlinearity: linear, dose-proportional pharmacokinetics stated (`start_drafts.LINEAR`). */
export const LINEAR_DRAFT = "linear";

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

/** Why the intake agent's last read stopped, in plain words, from its run's status and error (the owner, 2026-11-22:
 *  "read the proposal" on Start stopped with no word why). The server's own settings stay in the admin console and the
 *  server's log; this says what happened and who can change it. */
export function intakeStopped(status: string, error: string | null | undefined): string {
  const e = (error ?? "").toLowerCase();
  if (status === "INCOMPLETE" || /stopped after \d+ turns/.test(e)) {
    return "it used all its turns, and its short passes then filled what Start still needed";
  }
  if (/context window|context length|prompt was cut|too large|too long/.test(e)) {
    return "the proposal and the agent's instructions are longer than the AI model on this server can read at once "
      + "(its context window); an administrator can raise the window on the server, or choose another model for the "
      + "intake agent in Admin → Agents";
  }
  if (/daily limit|per day/.test(e)) {
    return "the AI model's daily allowance at its provider is used up; it renews within a day, or an administrator can "
      + "choose another model for the intake agent in Admin → Agents";
  }
  if (/rejected the key|http 401|http 403/.test(e)) {
    return "the AI provider refused the key; an administrator can check it in Admin → Keys";
  }
  if (/does not serve the model/.test(e)) {
    return "the AI provider does not serve the model chosen for the intake agent; an administrator can choose another "
      + "in Admin → Agents";
  }
  if (/unavailable|timed out|timeout|connect/.test(e)) return "the AI model could not be reached; read the proposal again later";
  return "the AI model stopped with an error (the run's record has it)";
}
