"use client";

import { useState } from "react";

import { DocumentViewer } from "@/components/brief/DocumentViewer";
import { InlineIssue } from "@/components/kit";
import { Dialog } from "@/components/kit/Dialog";
import { Fields } from "@/components/start/Blocks";
import { narrow, send } from "@/lib/api";
import type { BriefView, Citation } from "@/lib/brief";
import { useMutation, useResource } from "@/lib/hooks";
import { marks as startMarks, type BriefChange } from "@/lib/start";

type Focus = { sha256: string; page: number; quote: string | null } | null;

/** One list of the brief (the products, the populations), shown where it is used (page review 1, the owner's decision 3
 *  of 2026-10-29: Start no longer shows them). Each item's fields show their source and are changed in place; an item
 *  is added at the end and removed with the reason, which the brief keeps. The data plan follows every change. */
export function BriefList({ projectId, group, fields, title, lede, testId }: {
  projectId: string; group: "products" | "populations"; fields: string[]; title: string; lede: string; testId: string;
}) {
  const page = useResource("/api/v1/projects/{project_id}/brief", { project_id: projectId }, { select: (d) => narrow<BriefView>(d) });
  const docs = useResource("/api/v1/projects/{project_id}/documents", { project_id: projectId });
  const { run } = useMutation();
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus>(null);
  const view = page.data;
  if (!view) return null;
  const def = view.catalog.groups.find((g) => g.id === group);
  if (!def) return null;
  const items = view.brief.groups[group] ?? [];
  const noun = def.label.toLowerCase().replace(/s$/, "");
  const shown = def.fields.filter((f) => fields.includes(f.id)).map((f) => f.id);
  const paths = (i: number) => shown.map((f) => `${group}[${i}].${f}`);
  const open = (c: Citation) => setFocus({ sha256: c.doc_sha256, page: c.page, quote: c.quote });

  async function save(changes: BriefChange[]): Promise<string | null> {
    const { problem: refused } = await run(() => send("put", "/api/v1/projects/{project_id}/brief", { project_id: projectId }, { changes }));
    return refused;
  }

  async function answer(questionId: string, text: string, status: "answered" | "accepted_as_limitation") {
    const { problem: refused } = await run(() => send("post", "/api/v1/projects/{project_id}/brief/questions/{question_id}",
      { project_id: projectId, question_id: questionId }, { answer: text, status }));
    setProblem(refused);
  }

  async function remove(index: number) {
    const { problem: refused } = await run(() => send("post", "/api/v1/projects/{project_id}/brief/items:remove",
      { project_id: projectId }, { group, index, reason: reason.trim() }));
    setProblem(refused);
    if (!refused) { setRemoving(null); setReason(""); }
  }

  const marks = startMarks(view, answer);
  return (
    <section className="card brief-list" data-testid={testId}>
      <h3 style={{ marginTop: 0 }}>{title} <span className="muted">· {items.length}</span></h3>
      <p className="muted" style={{ marginTop: 0 }}>{lede}</p>
      {items.map((_, i) => (
        <div key={i} className="note-item" data-testid={`${testId}-${i}`}>
          <Fields view={view} paths={paths(i)} save={save} open={open} marks={marks} />
          {removing === i ? (
            <div className="row" style={{ gap: 6 }}>
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="why it goes (kept with the brief)"
                     aria-label={`why ${noun} ${i + 1} goes`} style={{ flex: 1 }} />
              <button type="button" className="btn" disabled={!reason.trim()} onClick={() => remove(i)}>Remove it</button>
              <button type="button" className="btn" onClick={() => setRemoving(null)}>Keep it</button>
            </div>
          ) : (
            <button type="button" className="link-btn" data-testid={`${testId}-${i}-remove`}
                    onClick={() => { setRemoving(i); setReason(""); }}>Remove this {noun}</button>
          )}
        </div>
      ))}
      {adding ? (
        <div className="note-item adding" data-testid={`${testId}-new`}>
          <p className="muted" style={{ margin: "0 0 4px", fontSize: 13 }}>A new {noun}: it is kept once one of its fields is saved.</p>
          <Fields key={items.length} view={view} paths={paths(items.length)} save={save} open={open} marks={marks} />
          <button type="button" className="link-btn" onClick={() => setAdding(false)}>Done</button>
        </div>
      ) : (
        <button type="button" className="btn" data-testid={`${testId}-add`} onClick={() => setAdding(true)}>Add a {noun}</button>
      )}
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
      {focus && (docs.data?.documents.length ?? 0) > 0 && (
        <Dialog title="Where the value comes from" size="wide" onClose={() => setFocus(null)} testId={`${testId}-source`}>
          <DocumentViewer projectId={projectId} documents={docs.data?.documents ?? []} focus={focus} />
          <div className="dialog-actions">
            <button type="button" className="btn" onClick={() => setFocus(null)}>Close</button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
