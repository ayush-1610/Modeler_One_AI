"use client";

// The Projects list (page review 1; the console redesign's P-03): each project with its steps, its next action, its
// owner and its record, and archive in place of delete. A project is a Part 11 record, so it is never erased: archiving
// hides it from this list and keeps everything it holds; it is shown again on request and restored. Both need a reason,
// kept in the audit trail. Only the project's owner archives it (the API's rule, `ownership`): the others see who does.

import Link from "next/link";
import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Dialog } from "@/components/kit/Dialog";
import { StepsMini, Table, type Column } from "@/components/kit/Table";
import { RiskBadge } from "@/components/kit/Badge";
import { send } from "@/lib/api";
import { useMutation, type After } from "@/lib/hooks";
import { nextHref, standing } from "@/lib/portfolio";
import type { Project } from "@/lib/types";

type Pending = { project: Project; action: "archive" | "restore" } | null;
/** A project archived or restored: the list of projects, drawn on the server, and read in the browser. */
const ARCHIVED: After = { reads: ["/api/v1/projects"], server: true };
const RISK = { low: 1, medium: 2, high: 3 } as Record<string, number>;

export function ProjectsTable({ projects, me, title = "Projects", limit, actions, testId = "projects-table" }: {
  projects: Project[];
  /** The signed-in person's id: their own projects show Archive and Restore. */
  me?: string | null;
  title?: string;
  /** Home's short list: the first few, no archive controls. */
  limit?: number;
  actions?: React.ReactNode;
  testId?: string;
}) {
  const { run, busy } = useMutation();
  const [showArchived, setShowArchived] = useState(false);
  const [pending, setPending] = useState<Pending>(null);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const archived = projects.filter((p) => p.archived);
  const listed = (showArchived ? projects : projects.filter((p) => !p.archived)).slice(0, limit ?? undefined);
  const mine = (p: Project) => !p.owner || p.owner === me;

  function ask(project: Project, action: "archive" | "restore") {
    setPending({ project, action });
    setReason("");
    setProblem(null);
  }

  async function confirm() {
    if (!pending) return;
    const route = pending.action === "archive" ? "/api/v1/projects/{project_id}:archive" : "/api/v1/projects/{project_id}:restore";
    const result = await run(() => send("post", route, { project_id: pending.project.id }, { reason: reason.trim() }), ARCHIVED);
    if (result.problem) setProblem(result.problem);
    else setPending(null);
  }

  const columns: Column<Project>[] = [
    { key: "name", label: "Project", sort: (p) => p.name.toLowerCase(), render: (p) => (
      <>
        <Link href={`/projects/${encodeURIComponent(p.id)}`}>{p.name}</Link>
        {p.archived && (
          <div className="muted fs-12" data-testid={`project-archived-${p.id}`}>
            archived by {p.archived.by} on {p.archived.at.slice(0, 10)}: {p.archived.reason}
          </div>
        )}
      </>
    ) },
    { key: "compounds", label: "Drug", sort: (p) => p.compounds.join(", "), render: (p) => p.compounds.join(", ") },
    { key: "steps", label: "Steps", render: (p) => <StepsMini steps={p.steps} /> },
    { key: "next", label: "Next action", render: (p) => (p.archived ? <span className="muted">Archived</span>
      : <Link href={nextHref(p)}>{standing(p.steps).next}</Link>) },
    { key: "risk", label: "Risk", sort: (p) => RISK[p.risk ?? ""] ?? 0, render: (p) => <RiskBadge rating={p.risk} /> },
    { key: "questions", label: "Open questions", num: true, sort: (p) => p.openQuestions, render: (p) => p.openQuestions },
    ...(limit ? [] : [
      { key: "owner", label: "Owner", sort: (p: Project) => p.owner_name ?? "", render: (p: Project) => p.owner_name ?? <span className="muted">—</span> },
      { key: "record", label: "Record", render: (p: Project) => <Link href={`/projects/${encodeURIComponent(p.id)}/history`} data-testid={`project-history-${p.id}`}>History</Link> },
      { key: "act", label: "Actions", render: (p: Project) => (mine(p) ? (
        <button type="button" className="btn small" disabled={busy} data-testid={`project-${p.archived ? "restore" : "archive"}-${p.id}`}
                onClick={() => ask(p, p.archived ? "restore" : "archive")}>{p.archived ? "Restore" : "Archive"}</button>
      ) : <span className="muted fs-12" title={`Only the owner, ${p.owner_name ?? p.owner}, archives it`}>owner only</span>) },
    ]),
  ];

  return (
    <>
      <Table title={title} count={limit ? null : listed.length} actions={actions} columns={columns} rows={listed} rowKey={(p) => p.id}
             rowTestId={(p) => `project-row-${p.id}`} testId={testId}
             filter={limit ? undefined : { placeholder: "Find a project or drug", text: (p) => `${p.name} ${p.compounds.join(" ")} ${p.owner_name ?? ""}`, testId: "projects-filter" }}
             tools={!limit && archived.length > 0 && (
               <button type="button" className="btn small" data-testid="projects-show-archived" onClick={() => setShowArchived(!showArchived)}>
                 {showArchived ? "Hide archived" : `Show archived (${archived.length})`}
               </button>
             )}
             empty={<>No projects yet. <Link href="/projects/start">Create one</Link> from a client&apos;s proposal.</>} />
      {pending && (
        <Dialog title={`${pending.action === "archive" ? "Archive" : "Restore"} ${pending.project.name}`} size="narrow"
                onClose={() => setPending(null)} testId="project-archive-dialog">
          <p className="muted">
            {pending.action === "archive"
              ? "The project is hidden from this list. Nothing it holds is changed or erased: its plan, campaigns and record stay, and it can be restored."
              : "The project is shown in this list again."}
          </p>
          <label htmlFor="project-archive-reason" className="muted fs-13">Why (kept in the audit trail)</label>
          <textarea id="project-archive-reason" rows={2} value={reason} className="w-full" data-testid="project-archive-reason"
                    onChange={(e) => setReason(e.target.value)}
                    placeholder={pending.action === "archive" ? "e.g. a test project, not client work" : "e.g. archived by mistake"} />
          {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
          <div className="dialog-actions">
            <button type="button" className="btn" onClick={() => setPending(null)}>Cancel</button>
            <button type="button" className="btn primary" disabled={busy || !reason.trim()} data-testid="project-archive-confirm"
                    onClick={confirm}>{pending.action === "archive" ? "Archive" : "Restore"}</button>
          </div>
        </Dialog>
      )}
    </>
  );
}
