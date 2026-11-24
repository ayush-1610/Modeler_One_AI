// The portfolio's reading of the projects (the console redesign, slice 2): where each project stands, and the person's
// work across projects. Pure functions over what the API answered (`GET /projects?with=steps,owner`, `GET /campaigns`,
// `GET /escalations`, `GET /me`), shared by Home, Your work, Projects and the top bar's count.
//
// Your work is a list of links (the owner's decision G1-3): nothing is decided in it; each item opens the page where it
// is decided. An item is listed only for someone who may act on it: a project's owner for its steps, a reviewer it is
// shared with for its signature, and whoever the API says may decide an escalation (`can_decide`, R-S02).

import { STEP_ROUTES, type StepId, type StepRow } from "@/lib/pipeline";
import type { Campaign, Escalation, Project } from "@/lib/types";
import { stepReason } from "@/lib/words";

export type Standing = "needs_you" | "running" | "done" | "not_started" | "unknown";
export type WorkKind = "To sign" | "To decide" | "To confirm";
export type WorkItem = {
  key: string; kind: WorkKind; what: string; detail: string | null;
  projectId: string | null; projectName: string | null; step: string; href: string;
};

/** What a project's next action is called, by the step it waits at. */
export const NEXT: Record<StepId, string> = {
  start: "Confirm the brief", inputs: "Finish the inputs", review: "Sign the MAP", run: "Run the campaign",
};
export const STEP_NAME: Record<StepId, string> = { start: "Start", inputs: "Data", review: "Review & sign", run: "Run" };
export const STANDING_WORD: Record<Standing, string> = {
  needs_you: "Needs you", running: "Running", done: "Done", not_started: "Not started", unknown: "Steps not read",
};

/** Where a project stands, read from its four steps: the step that waits on a person first, then one that runs. */
export function standing(steps: StepRow[] | null | undefined): { state: Standing; focus: StepId | null; next: string; reason: string | null } {
  if (!steps || steps.length === 0) return { state: "unknown", focus: null, next: "Open the project", reason: null };
  const waiting = steps.find((s) => s.state === "needs_you");
  const running = steps.find((s) => s.state === "running");
  if (waiting) return { state: "needs_you", focus: waiting.step, next: NEXT[waiting.step], reason: waiting.reasons[0] ?? null };
  if (running) return { state: "running", focus: running.step, next: "Watch the run", reason: running.reasons[0] ?? null };
  if (steps.every((s) => s.state === "done")) return { state: "done", focus: "run", next: "Open the results", reason: null };
  const first = steps.find((s) => s.state !== "done") ?? steps[0]!;
  return { state: "not_started", focus: first.step, next: NEXT[first.step], reason: first.reasons[0] ?? null };
}

/** Where a project's next action is done. */
export function nextHref(p: Project): string {
  const st = standing(p.steps);
  return st.focus ? STEP_ROUTES[st.focus](encodeURIComponent(p.id)) : `/projects/${encodeURIComponent(p.id)}`;
}

/** Everything that waits on this person across their projects, as links; escalations first (a decision is never last). */
export function workItems(projects: Project[], escalations: Escalation[], campaigns: Campaign[],
                          me: { user_id: string; roles: string[] } | null): WorkItem[] {
  const reviewer = me?.roles.includes("modeler-reviewer") ?? false;
  const byId = new Map(projects.map((p) => [p.id, p]));
  const projectOf = new Map(campaigns.map((c) => [c.id, c.project]));
  const decided = new Set<string>();
  const items: WorkItem[] = [];
  for (const e of escalations.filter((x) => x.can_decide)) {
    const pid = projectOf.get(e.campaignId) ?? null;
    if (pid) decided.add(pid);
    items.push({
      key: `esc-${e.id}`, kind: "To decide", what: `Decide the ${e.stage} escalation`,
      detail: e.reasonCode.replace(/_/g, " ").toLowerCase(), projectId: pid, projectName: pid ? byId.get(pid)?.name ?? pid : null,
      step: `Run · ${e.campaignId}`, href: `/campaigns/${encodeURIComponent(e.campaignId)}`,
    });
  }
  for (const p of projects) {
    if (p.archived || !p.steps) continue;
    // the owner changes the project; with no owner on record its members do, as the API allows
    const mine = !p.owner || p.owner === me?.user_id;
    for (const s of p.steps.filter((x) => x.state === "needs_you")) {
      if (s.step === "run" && decided.has(p.id)) continue;            // its escalation is listed above
      const may = s.step === "review" ? mine || reviewer : mine;
      if (!may) continue;
      items.push({
        key: `step-${p.id}-${s.step}`, kind: s.step === "review" ? "To sign" : s.step === "run" ? "To decide" : "To confirm",
        what: NEXT[s.step], detail: s.reasons[0] ? stepReason(s.reasons[0], s.formulation) : null,
        projectId: p.id, projectName: p.name, step: STEP_NAME[s.step], href: STEP_ROUTES[s.step](encodeURIComponent(p.id)),
      });
    }
  }
  return items;
}
