"use client";

// The project document library (docs/plans/2026-10-28-project-document-library.md, PR 1; the owner's decisions 10–13 of
// 2026-10-29): every document of this project, who added it, and what the project took from it, computed from what
// cites it (an evidence value, an observed dataset, a brief field). Search, filters and sorting run over the table; a
// document opens on its pages. Each project's library is its own: nothing here is shared with another project.
// PR 2: what each document relates to (a step and, optionally, a task), and withdrawal with a reason (answer 12): a
// withdrawn document stays here, marked, and the agents no longer use it; it can be restored, with a reason too.

import Link from "next/link";
import { useMemo, useState } from "react";

import { DocumentViewer } from "@/components/brief/DocumentViewer";
import { EmptyState, InlineIssue } from "@/components/kit";
import { Dialog } from "@/components/kit/Dialog";
import { RELATED_STEPS } from "@/components/library/AddData";
import { send, type Schema } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";
import { STEP_ROUTES, type StepId } from "@/lib/pipeline";

type Row = Schema<"LibraryRowView">;
type Contribution = Schema<"ContributionView">;
type Sort = "newest" | "oldest" | "name";
type Change = { row: Row; action: "withdraw" | "restore" };
const STEP_LABEL = Object.fromEntries(RELATED_STEPS);

const ROLE: Record<string, string> = {
  proposal: "proposal", annex: "annex", context: "context", client_file: "client file", paper: "paper",
  retrieved_record: "retrieved record", other: "other",
};
const KIND: Record<Contribution["kind"], string> = { value: "value", dataset: "dataset", brief: "brief" };
const SHOWN = 3;

function Uses({ projectId, row }: { projectId: string; row: Row }) {
  const [all, setAll] = useState(false);
  if (!row.contributions.length) return <span className="muted">Nothing taken from it yet</span>;
  const shown = all ? row.contributions : row.contributions.slice(0, SHOWN);
  return (
    <ul className="library-uses">
      {shown.map((c, i) => (
        <li key={i}>
          <span className="chip neutral">{KIND[c.kind]}</span>{" "}
          <Link href={c.step === "start" ? STEP_ROUTES.start(projectId) : STEP_ROUTES.inputs(projectId)}>
            <code>{c.target}</code></Link> = {c.value}
          <span className="muted"> · {c.state.toLowerCase().replace(/_/g, " ")}{c.page ? ` · p.${c.page}` : ""}</span>
        </li>
      ))}
      {row.contributions.length > SHOWN && (
        <li><button type="button" className="link-btn" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `+ ${row.contributions.length - SHOWN} more`}</button></li>
      )}
    </ul>
  );
}

function RelatesTo({ projectId, row }: { projectId: string; row: Row }) {
  const r = row.relates_to;
  if (!r) return <span className="muted">not said</span>;
  return (
    <>
      <Link href={STEP_ROUTES[r.step as StepId](projectId)}>{STEP_LABEL[r.step] ?? r.step}</Link>
      {r.task && <div className="muted" style={{ fontSize: 12 }}>{r.task}</div>}
    </>
  );
}

/** Withdraw (or restore) a document: a reason is required, and kept in the audit trail. */
function ChangeDialog({ projectId, change, onClose }: { projectId: string; change: Change; onClose: () => void }) {
  const { run, busy } = useMutation();
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const { row, action } = change;
  const uses = row.contributions.length;

  async function confirm() {
    const params = { project_id: projectId, sha256: row.sha256 };
    const { problem } = action === "withdraw"
      ? await run(() => send("post", "/api/v1/projects/{project_id}/documents/{sha256}:withdraw", params, { reason: reason.trim() }))
      : await run(() => send("post", "/api/v1/projects/{project_id}/documents/{sha256}:restore", params, { reason: reason.trim() }));
    if (problem) setProblem(problem);
    else onClose();
  }

  return (
    <Dialog title={action === "withdraw" ? `Withdraw ${row.name}` : `Restore ${row.name}`} onClose={onClose} testId="library-change">
      {action === "withdraw" ? (
        <p>
          It stays in the library, marked as withdrawn, and the agents no longer list, search or read it. Nothing new is taken
          from it until it is restored.{" "}
          {uses > 0 && <>The {uses} {uses === 1 ? "thing" : "things"} already taken from it keep their source: reject them on
            Inputs if they must go.</>}
        </p>
      ) : (
        <p>It is used again: listed for the agents, and a source for new values.</p>
      )}
      <label className="add-data-field">
        <span>Why</span>
        <textarea rows={3} maxLength={500} value={reason} data-testid="library-reason" onChange={(e) => setReason(e.target.value)} />
      </label>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={busy || !reason.trim()}
                data-testid="library-confirm" onClick={confirm}>
          {action === "withdraw" ? "Withdraw" : "Restore"}
        </button>
      </div>
    </Dialog>
  );
}

export function LibraryTable({ projectId }: { projectId: string }) {
  const page = useResource("/api/v1/projects/{project_id}/library", { project_id: projectId });
  const docs = useResource("/api/v1/projects/{project_id}/documents", { project_id: projectId });
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("");
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState<Sort>("newest");
  const [open, setOpen] = useState<string | null>(null);
  const [change, setChange] = useState<Change | null>(null);
  const rows = useMemo(() => page.data?.documents ?? [], [page.data]);

  const shown = useMemo(() => {
    const words = query.trim().toLowerCase();
    const hit = (r: Row) => !words || [r.name, r.role, r.added_by, r.relates_to?.task ?? "", r.withdrawn?.reason ?? "",
      ...r.contributions.map((c) => `${c.target} ${c.value}`)].join(" ").toLowerCase().includes(words);
    const list = rows.filter((r) => hit(r) && (!role || r.role === role) && (!source || r.source === source)
      && (!status || (status === "withdrawn") === Boolean(r.withdrawn)));
    return [...list].sort((a, b) => sort === "name" ? a.name.localeCompare(b.name)
      : sort === "oldest" ? a.added_at.localeCompare(b.added_at) : b.added_at.localeCompare(a.added_at));
  }, [rows, query, role, source, status, sort]);

  if (page.problem) return <div className="banner err">{page.problem}</div>;
  if (!page.data) return <p className="muted">Loading the library…</p>;
  const roles = [...new Set(rows.map((r) => r.role))];

  return (
    <div data-testid="library">
      <div className="library-tools">
        <input type="search" aria-label="Search the library" placeholder="Search names, values, parameters…" value={query}
               data-testid="library-search" onChange={(e) => setQuery(e.target.value)} />
        <select aria-label="Role" value={role} data-testid="library-role" onChange={(e) => setRole(e.target.value)}>
          <option value="">every role</option>
          {roles.map((r) => <option key={r} value={r}>{ROLE[r] ?? r}</option>)}
        </select>
        <select aria-label="Added by" value={source} data-testid="library-source" onChange={(e) => setSource(e.target.value)}>
          <option value="">added by anyone</option>
          <option value="person">by a person</option>
          <option value="agent">by an agent</option>
          <option value="system">by the system</option>
        </select>
        <select aria-label="Status" value={status} data-testid="library-status" onChange={(e) => setStatus(e.target.value)}>
          <option value="">in use and withdrawn</option>
          <option value="current">in use</option>
          <option value="withdrawn">withdrawn</option>
        </select>
        <select aria-label="Sort" value={sort} data-testid="library-sort" onChange={(e) => setSort(e.target.value as Sort)}>
          <option value="newest">newest first</option>
          <option value="oldest">oldest first</option>
          <option value="name">by name</option>
        </select>
        <span className="muted">{shown.length} of {rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No documents yet">The proposal, and every file added with “+ Add data”, appear here.</EmptyState>
      ) : (
        <div className="table-scroll">
          <table className="library-table">
            <thead>
              <tr><th>Document</th><th>Added</th><th>Role</th><th>Relates to</th><th>Format</th><th className="num">Versions</th>
                <th>Data extracted / project contribution</th><th><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.sha256} data-testid={`library-row-${r.name}`} className={r.withdrawn ? "withdrawn" : undefined}>
                  <td>
                    <button type="button" className="link-btn" data-testid={`library-open-${r.name}`} onClick={() => setOpen(r.sha256)}>
                      {r.name}</button>
                    {r.withdrawn && (
                      <div className="library-withdrawn" data-testid={`library-withdrawn-${r.name}`}>
                        <span className="chip medium">withdrawn</span> {r.withdrawn.at.slice(0, 10)} by {r.withdrawn.by}: {r.withdrawn.reason}
                      </div>
                    )}
                  </td>
                  <td>{r.source === "person" ? r.added_by : r.source === "agent" ? `agent (${r.added_by.slice(6)})` : "system"}
                    <div className="muted" style={{ fontSize: 12 }}>{r.added_at.slice(0, 10)}</div></td>
                  <td>{ROLE[r.role] ?? r.role}</td>
                  <td><RelatesTo projectId={projectId} row={r} /></td>
                  <td>{r.format} · {r.n_pages} p.</td>
                  <td className="num">{r.versions}</td>
                  <td><Uses projectId={projectId} row={r} /></td>
                  <td>
                    <button type="button" className="btn tiny" data-testid={`library-${r.withdrawn ? "restore" : "withdraw"}-${r.name}`}
                            onClick={() => setChange({ row: r, action: r.withdrawn ? "restore" : "withdraw" })}>
                      {r.withdrawn ? "Restore" : "Withdraw"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {change && <ChangeDialog key={change.row.sha256} projectId={projectId} change={change} onClose={() => setChange(null)} />}
      {open && docs.data && (
        <Dialog title="The document" size="wide" onClose={() => setOpen(null)} testId="library-viewer">
          <DocumentViewer projectId={projectId} documents={docs.data.documents} focus={{ sha256: open, page: 1, quote: null }} />
          <div className="dialog-actions">
            <button type="button" className="btn" onClick={() => setOpen(null)}>Close</button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
