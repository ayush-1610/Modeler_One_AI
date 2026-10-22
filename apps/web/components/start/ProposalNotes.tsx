"use client";

import { useState } from "react";

import { Fields, OpenQuestions } from "@/components/start/Blocks";
import { InlineIssue } from "@/components/kit";
import { EMPTY_RECORD, type BriefView } from "@/lib/brief";
import type { Open, Save } from "@/lib/start";

const NOTE_GROUPS = ["products", "populations", "data_plan", "scenarios"];

export type Remove = (group: string, index: number, reason: string) => Promise<string | null>;

/** One list of the brief (the products, the populations, what the proposal says about data, the prediction scenarios),
 *  each item's fields edited in place; an item is added at the end and removed with the reason, which the brief keeps. */
function GroupList({ gid, view, save, open, remove }: { gid: string; view: BriefView; save: Save; open: Open; remove: Remove }) {
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const group = view.catalog.groups.find((g) => g.id === gid);
  if (!group) return null;
  const items = view.brief.groups[gid] ?? [];
  const noun = group.label.toLowerCase().replace(/s$/, "");
  // the short brief edits these fields of a scenario itself (route and food state), so they are not repeated here
  const short = new Set(view.catalog.short_group_fields[gid] ?? []);
  const paths = (i: number, all: boolean) => group.fields.filter((f) => all || !short.has(f.id)).map((f) => `${gid}[${i}].${f.id}`);
  return (
    <div className="note-group" data-testid={`notes-${gid}`}>
      <h3 className="start-sub">{group.label} <span className="muted">· {items.length}</span></h3>
      {items.map((_, i) => (
        <div key={i} className="note-item" data-testid={`notes-${gid}-${i}`}>
          <Fields view={view} paths={paths(i, false)} save={save} open={open} />
          {removing === i ? (
            <div className="row" style={{ gap: 6 }}>
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="why it goes (kept with the brief)"
                     aria-label={`why ${noun} ${i + 1} goes`} style={{ flex: 1 }} />
              <button type="button" className="btn" disabled={!reason.trim()} onClick={async () => {
                const refused = await remove(gid, i, reason);
                setProblem(refused);
                if (!refused) { setRemoving(null); setReason(""); }
              }}>Remove it</button>
              <button type="button" className="btn" onClick={() => setRemoving(null)}>Keep it</button>
            </div>
          ) : (
            <button type="button" className="link-btn" data-testid={`notes-${gid}-${i}-remove`}
                    onClick={() => { setRemoving(i); setReason(""); }}>Remove this {noun}</button>
          )}
        </div>
      ))}
      {adding ? (
        <div className="note-item adding" data-testid={`notes-${gid}-new`}>
          <p className="muted" style={{ margin: "0 0 4px", fontSize: 13 }}>A new {noun}: it is kept once one of its fields is saved.</p>
          <Fields key={items.length} view={view} paths={paths(items.length, true)} save={save} open={open} />
          <button type="button" className="link-btn" onClick={() => setAdding(false)}>Done</button>
        </div>
      ) : (
        <button type="button" className="btn" data-testid={`notes-${gid}-add`} onClick={() => setAdding(true)}>Add a {noun}</button>
      )}
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </div>
  );
}

/** Block 6, collapsed: everything else the proposal says (title, client, products, populations, doses…), kept for the
 *  report and never required, all edited here: the products, the populations, what the proposal says about data and the
 *  prediction scenarios, which the data checklist and the applications read. */
export function ProposalNotes({ view, save, open, remove, onAnswer }: {
  view: BriefView; save: Save; open: Open; remove: Remove;
  onAnswer: (id: string, text: string, status: "answered" | "accepted_as_limitation") => void;
}) {
  const short = new Set(view.catalog.short_brief);
  const fields = view.catalog.fields.filter((f) => !short.has(f.id));
  const filled = fields.filter((f) => (view.brief.fields[f.id] ?? EMPTY_RECORD).status !== "MISSING").length;
  const noteFields = new Set(fields.map((f) => f.id));
  return (
    <details className="card start-notes" data-testid="start-notes">
      <summary>
        <span className="start-block-n" aria-hidden>6</span>
        <span><strong>Proposal notes</strong> <span className="muted">· {filled} of {fields.length} filled · optional, kept for the report</span></span>
      </summary>
      <Fields view={view} paths={fields.map((f) => f.id)} save={save} open={open} />
      {NOTE_GROUPS.map((gid) => <GroupList key={gid} gid={gid} view={view} save={save} open={open} remove={remove} />)}
      <OpenQuestions view={view} fields={noteFields} onAnswer={onAnswer} />
    </details>
  );
}
