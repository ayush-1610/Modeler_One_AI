"use client";

// The Projects list (page review 1): each project with its record, and archive in place of delete. A project is a Part 11
// record, so it is never erased: archiving hides it from this list and keeps everything it holds; it is shown again on
// request and restored. Both need a reason, kept in the audit trail.

import Link from "next/link";
import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Dialog } from "@/components/kit/Dialog";
import { SortHeader } from "@/components/kit/SortableTable";
import { RiskChip } from "@/components/ui";
import { send } from "@/lib/api";
import { useMutation } from "@/lib/hooks";
import { ordinal, useTableView } from "@/lib/tableView";
import type { Project } from "@/lib/types";

// sortable by its heads, in the order the projects arrive until one is pressed (the 2026-11-11 audit, item 11); not paged,
// so a project just made is never on a later page
const riskOrder = ordinal(["low", "medium", "high"]);
const PROJECT_KEYS = {
  name: (p: Project) => p.name, compounds: (p: Project) => p.compounds.join(", "),
  questions: (p: Project) => p.openQuestions, risk: (p: Project) => riskOrder(p.risk),
};

type Pending = { project: Project; action: "archive" | "restore" } | null;

export function ProjectsTable({ projects }: { projects: Project[] }) {
  const { run, busy } = useMutation();
  const [showArchived, setShowArchived] = useState(false);
  const [pending, setPending] = useState<Pending>(null);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const archived = projects.filter((p) => p.archived);
  const view = useTableView({ rows: showArchived ? projects : projects.filter((p) => !p.archived), keys: PROJECT_KEYS });
  const shown = view.visible;

  function ask(project: Project, action: "archive" | "restore") {
    setPending({ project, action });
    setReason("");
    setProblem(null);
  }

  async function confirm() {
    if (!pending) return;
    const route = pending.action === "archive" ? "/api/v1/projects/{project_id}:archive" : "/api/v1/projects/{project_id}:restore";
    const result = await run(() => send("post", route, { project_id: pending.project.id }, { reason: reason.trim() }));
    if (result.problem) setProblem(result.problem);
    else setPending(null);
  }

  return (
    <>
      {archived.length > 0 && (
        <div className="row" style={{ justifyContent: "flex-end", marginBottom: 8 }}>
          <button type="button" className="btn" data-testid="projects-show-archived" onClick={() => setShowArchived(!showArchived)}>
            {showArchived ? "Hide archived" : `Show archived (${archived.length})`}
          </button>
        </div>
      )}
      <table>
        <thead>
          <tr>
            <SortHeader view={view} col="name" label="Project" />
            <SortHeader view={view} col="compounds" label="Compounds" />
            <SortHeader view={view} col="questions" label="Open questions" numeric />
            <SortHeader view={view} col="risk" label="Program risk" />
            <th>Record</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {shown.map((p) => (
            <tr key={p.id} className={p.archived ? "project-archived" : ""} data-testid={`project-row-${p.id}`}>
              <td>
                <Link href={`/projects/${p.id}`}>{p.name}</Link>
                {p.archived && (
                  <div className="muted" style={{ fontSize: 12 }} data-testid={`project-archived-${p.id}`}>
                    archived by {p.archived.by} on {p.archived.at.slice(0, 10)}: {p.archived.reason}
                  </div>
                )}
              </td>
              <td>{p.compounds.join(", ")}</td>
              <td className="num">{p.openQuestions}</td>
              <td><RiskChip rating={p.risk} /></td>
              <td><Link href={`/projects/${p.id}/history`} data-testid={`project-history-${p.id}`}>History</Link></td>
              <td className="num">
                <button type="button" className="btn" disabled={busy} data-testid={`project-${p.archived ? "restore" : "archive"}-${p.id}`}
                        onClick={() => ask(p, p.archived ? "restore" : "archive")}>{p.archived ? "Restore" : "Archive"}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {pending && (
        <Dialog title={`${pending.action === "archive" ? "Archive" : "Restore"} ${pending.project.name}`} size="narrow"
                onClose={() => setPending(null)} testId="project-archive-dialog">
          <p className="muted">
            {pending.action === "archive"
              ? "The project is hidden from this list. Nothing it holds is changed or erased: its plan, campaigns and record stay, and it can be restored."
              : "The project is shown in this list again."}
          </p>
          <label htmlFor="project-archive-reason" className="muted" style={{ fontSize: 13 }}>Why (kept in the audit trail)</label>
          <textarea id="project-archive-reason" rows={2} value={reason} style={{ width: "100%" }} data-testid="project-archive-reason"
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
