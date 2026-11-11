"use client";

// The project document library (docs/plans/2026-10-28-project-document-library.md, PR 1; the owner's decisions 10–13 of
// 2026-10-29): every document of this project, who added it, and what the project took from it, computed from what
// cites it (an evidence value, an observed dataset, a brief field). Search, filters and sorting run over the table; a
// document opens on its pages. Each project's library is its own: nothing here is shared with another project.
// PR 2: what each document relates to (a step and, optionally, a task), and withdrawal with a reason (answer 12): a
// withdrawn document stays here, marked, and the agents no longer use it; it can be restored, with a reason too.
// PR 3: what an agent fetched says where from (with its link) and whether the full text or only the abstract is held.
// A client file's tag (plan 2026-11-03 §3.1, option D): changed here at any time, with no reason asked; another tag the
// content suggests is shown with what prompted it, to use or keep; a scan or an image is marked "needs OCR".

import Link from "next/link";
import { useMemo, useState } from "react";

import { DocumentViewer } from "@/components/brief/DocumentViewer";
import { EmptyState, InlineIssue } from "@/components/kit";
import { Dialog } from "@/components/kit/Dialog";
import { SortHeader, TableMore } from "@/components/kit/SortableTable";
import { RELATED_STEPS } from "@/components/library/AddData";
import { send, type Schema } from "@/lib/api";
import { TAG_KINDS, TAG_LABELS, type TagKind, tagLabel } from "@/lib/fileTags";
import { useMutation, useResource } from "@/lib/hooks";
import { STEP_ROUTES, type StepId } from "@/lib/pipeline";
import { type SortState, useTableView } from "@/lib/tableView";

type Row = Schema<"LibraryRowView">;
type Contribution = Schema<"ContributionView">;
type Sort = "newest" | "oldest" | "name";
const SORTS: Record<Sort, NonNullable<SortState>> = {
  newest: { col: "added", dir: "descending" }, oldest: { col: "added", dir: "ascending" }, name: { col: "name", dir: "ascending" },
};
const LIBRARY_KEYS = {
  name: (r: Row) => r.name, added: (r: Row) => r.added_at, role: (r: Row) => ROLE[r.role] ?? r.role, versions: (r: Row) => r.versions,
};
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
      {r.task && <div className="muted fs-12">{r.task}</div>}
    </>
  );
}

/** A client file's tag, changeable at any time; the content's proposal beside it; a scan marked for OCR. */
function TagCell({ projectId, row }: { projectId: string; row: Row }) {
  const { run, busy } = useMutation();
  const [problem, setProblem] = useState<string | null>(null);
  if (row.role !== "client_file") return row.needs_ocr ? <div><span className="chip medium">needs OCR</span></div> : null;
  const proposal = row.tag_proposal?.decided === "open" ? row.tag_proposal : null;

  async function retag(kind: TagKind) {
    const { problem } = await run(() => send("post", "/api/v1/projects/{project_id}/documents/{sha256}:tag",
      { project_id: projectId, sha256: row.sha256 }, { kind, study: kind === "clinical" ? row.tag?.study ?? "" : "" }));
    setProblem(problem);
  }

  return (
    <div className="library-tag" data-testid={`library-tag-${row.name}`}>
      <select aria-label={`Tag of ${row.name}`} value={row.tag?.kind ?? "other"} disabled={busy}
              data-testid={`library-tag-select-${row.name}`} onChange={(e) => retag(e.target.value as TagKind)}>
        {TAG_KINDS.map((kind) => <option key={kind} value={kind}>{TAG_LABELS[kind]}</option>)}
      </select>
      {row.tag?.study && <div className="muted fs-12">{row.tag.study}</div>}
      {row.needs_ocr && <div><span className="chip medium">needs OCR</span></div>}
      {proposal && (
        <div className="library-tag-proposal">
          The content suggests “{tagLabel(proposal.kind)}”: {proposal.why}.{" "}
          <button type="button" className="link-btn" disabled={busy} data-testid={`library-tag-use-${row.name}`}
                  onClick={() => retag(proposal.kind)}>Use it</button>{" · "}
          <button type="button" className="link-btn" disabled={busy}
                  onClick={() => retag(row.tag?.kind ?? "other")}>Keep “{tagLabel(row.tag?.kind)}”</button>
        </div>
      )}
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </div>
  );
}

const HELD: Record<string, string> = { full_text: "full text (open access)", abstract: "abstract only", page: "web page" };

/** Where an agent took a document from, and what of it the project holds (PR 3: open-access full text only). */
function Retrieved({ row }: { row: Row }) {
  const r = row.retrieved;
  if (!r) return null;
  const id = r.pmid ? `PMID ${r.pmid}` : r.doi ? `doi ${r.doi}` : "";
  return (
    <div className="library-retrieved" data-testid={`library-retrieved-${row.name}`}>
      {r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.source}</a> : r.source}
      {id && <> · {id}</>}
      <div><span className={`chip ${r.held === "abstract" ? "medium" : "neutral"}`}>{HELD[r.held] ?? r.held}</span></div>
    </div>
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
  const [open, setOpen] = useState<string | null>(null);
  const [change, setChange] = useState<Change | null>(null);
  const rows = useMemo(() => page.data?.documents ?? [], [page.data]);

  const filtered = useMemo(() => {
    const words = query.trim().toLowerCase();
    const hit = (r: Row) => !words || [r.name, r.role, r.added_by, r.relates_to?.task ?? "", r.withdrawn?.reason ?? "",
      r.retrieved ? `${r.retrieved.source} ${r.retrieved.pmid} ${r.retrieved.doi} ${HELD[r.retrieved.held] ?? ""}` : "",
      ...r.contributions.map((c) => `${c.target} ${c.value}`)].join(" ").toLowerCase().includes(words);
    return rows.filter((r) => hit(r) && (!role || r.role === role) && (!source || r.source === source)
      && (!status || (status === "withdrawn") === Boolean(r.withdrawn)));
  }, [rows, query, role, source, status]);
  // the Sort select and the column heads drive one order (the 2026-11-11 audit, item 11); newest first, as before
  const view = useTableView({ rows: filtered, keys: LIBRARY_KEYS, pageSize: 50, initialSort: SORTS.newest,
                              filterKey: `${query}|${role}|${source}|${status}` });
  const shown = view.visible;
  const sort = (Object.keys(SORTS) as Sort[]).find((k) => SORTS[k].col === view.sort?.col && SORTS[k].dir === view.sort?.dir) ?? "custom";

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
        <select aria-label="Sort" value={sort} data-testid="library-sort"
                onChange={(e) => { if (e.target.value in SORTS) view.setSort(SORTS[e.target.value as Sort]); }}>
          {sort === "custom" && <option value="custom">{view.sort ? "as the column heads say" : "as added to the project"}</option>}
          <option value="newest">newest first</option>
          <option value="oldest">oldest first</option>
          <option value="name">by name</option>
        </select>
        <span className="muted">{filtered.length} of {rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No documents yet">The proposal, and every file added with “+ Add data”, appear here.</EmptyState>
      ) : (
        <div className="table-scroll">
          <table className="library-table">
            <thead>
              <tr><SortHeader view={view} col="name" label="Document" /><SortHeader view={view} col="added" label="Added" />
                <SortHeader view={view} col="role" label="Role and tag" /><th>Relates to</th><th>Format</th>
                <SortHeader view={view} col="versions" label="Versions" numeric />
                <th>Data extracted / project contribution</th></tr>
            </thead>
            <tbody className="paged-rows">
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
                    {/* under the name, not in a last column: on a phone that column was off-screen (audit 2, item 8) */}
                    <div className="library-action">
                      <button type="button" className="btn tiny" data-testid={`library-${r.withdrawn ? "restore" : "withdraw"}-${r.name}`}
                              aria-label={`${r.withdrawn ? "Restore" : "Withdraw"} ${r.name}`}
                              onClick={() => setChange({ row: r, action: r.withdrawn ? "restore" : "withdraw" })}>
                        {r.withdrawn ? "Restore" : "Withdraw"}
                      </button>
                    </div>
                  </td>
                  <td>{r.source === "person" ? r.added_by : r.source === "agent" ? `agent (${r.added_by.slice(6)})` : "system"}
                    <div className="muted fs-12">{r.added_at.slice(0, 10)}</div>
                    <Retrieved row={r} /></td>
                  <td>{ROLE[r.role] ?? r.role}<TagCell projectId={projectId} row={r} /></td>
                  <td><RelatesTo projectId={projectId} row={r} /></td>
                  <td>{r.format} · {r.n_pages} p.</td>
                  <td className="num">{r.versions}</td>
                  <td><Uses projectId={projectId} row={r} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > 0 && <TableMore view={view} noun="documents" testId="library-more" />}
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
