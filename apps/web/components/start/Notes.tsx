"use client";

// The proposal notes (map rows p1-title, p1-type, p1-admin, p1-drugother, p1-prodother, p1-scen-dose, p1-scope-other):
// everything else the proposal says, kept for the report and never required; and the open questions (p1-questions),
// answered or accepted as a limitation. Products, populations and the proposal's own data-plan statements are kept
// here until Inputs and Review & sign are rebuilt (R3, R4).

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { FieldRow, type OpenQuote, type Run, type Save } from "@/components/start/Fields";
import { send } from "@/lib/api";
import { filled, shown, type NoteGroup, type StartPage } from "@/lib/start";

function GroupNotes({ projectId, group, onSave, onOpen, run, busy }: {
  projectId: string; group: NoteGroup; onSave: Save; onOpen: OpenQuote; run: Run; busy: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const noun = group.label.toLowerCase().replace(/ \(.*\)$/, "").replace(/s$/, "");

  async function remove(index: number) {
    const { problem: failed } = await run(() => send("post", "/api/v1/projects/{project_id}/brief/items:remove",
      { project_id: projectId }, { group: group.id, index, reason: `${noun} ${index + 1} removed at Start` }));
    setProblem(failed);
  }

  return (
    <section className="note-group" data-testid={`notes-${group.id}`}>
      <div className="spread">
        <h3>{group.label}</h3>
        {!adding && <button type="button" className="link-btn" disabled={busy} onClick={() => setAdding(true)}>Add</button>}
      </div>
      {group.warnings.map((w) => <InlineIssue key={w}>{w}</InlineIssue>)}
      {group.items.length === 0 && !adding && <p className="muted">None stated.</p>}
      {group.items.map((fields, index) => (
        <details key={index} className="note-item">
          <summary>
            <span>{fields.filter(filled).slice(0, 3).map(shown).join(" · ") || `${noun} ${index + 1}`}</span>
            <button type="button" className="link-btn" disabled={busy} onClick={(e) => { e.preventDefault(); remove(index); }}>
              Remove</button>
          </summary>
          <div className="notes-grid">
            {fields.map((f) => <FieldRow key={f.path} field={f} onSave={onSave} onOpen={onOpen} busy={busy} />)}
          </div>
        </details>
      ))}
      {adding && (
        <div className="note-item adding">
          <p className="muted">A new {noun}: fill what you know; it is kept once one field is saved.</p>
          <div className="notes-grid">
            {group.blank.map((f) => <FieldRow key={f.path} field={f} onSave={async (changes, reason) => {
              const failed = await onSave(changes, reason);
              if (!failed) setAdding(false);
              return failed;
            }} onOpen={onOpen} busy={busy} />)}
          </div>
          <button type="button" className="btn" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      )}
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </section>
  );
}

export function ProposalNotes({ projectId, view, onSave, onOpen, run, busy }: {
  projectId: string; view: StartPage; onSave: Save; onOpen: OpenQuote; run: Run; busy: boolean;
}) {
  const [adding, setAdding] = useState<string | null>(null);
  const stated = view.notes.filter((f) => filled(f) || f.path === adding);
  const unstated = view.notes.filter((f) => !filled(f) && f.path !== adding);
  const noted = view.notes.filter(filled).length + view.note_groups.reduce((n, g) => n + g.items.length, 0);
  return (
    <details className="proposal-notes" data-testid="proposal-notes">
      <summary>
        <strong>Proposal notes</strong>
        <span className="muted"> · {noted} noted · everything else the proposal says, kept for the report and never required</span>
      </summary>
      {stated.length > 0 && (
        <div className="notes-grid">
          {stated.map((f) => (
            <FieldRow key={f.path} field={f} onSave={onSave} onOpen={onOpen} busy={busy} open={f.path === adding}
                      onClose={() => setAdding(null)} />
          ))}
        </div>
      )}
      {unstated.length > 0 && (
        <p className="unstated" data-testid="notes-unstated">
          <span className="muted">Not stated:</span>{" "}
          {unstated.map((f) => (
            <button key={f.path} type="button" className="link-btn" data-testid={`note-add-${f.path}`} disabled={busy}
                    onClick={() => setAdding(f.path)}>{f.label}</button>
          ))}
        </p>
      )}
      {view.note_groups.map((g) => (
        <GroupNotes key={g.id} projectId={projectId} group={g} onSave={onSave} onOpen={onOpen} run={run} busy={busy} />
      ))}
    </details>
  );
}

export function Questions({ projectId, view, label, run, busy }: {
  projectId: string; view: StartPage; label: (path: string) => string; run: Run; busy: boolean;
}) {
  const [text, setText] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const open = view.questions.filter((q) => q.status === "open");
  const settled = view.questions.filter((q) => q.status !== "open");
  if (!view.questions.length) return null;

  async function answer(id: string, status: "answered" | "accepted_as_limitation") {
    const { problem: failed } = await run(() => send("post", "/api/v1/projects/{project_id}/brief/questions/{question_id}",
      { project_id: projectId, question_id: id }, { answer: (text[id] ?? "").trim(), status }));
    setProblem(failed);
  }

  return (
    <section className="questions" data-testid="questions">
      <h3>Open questions {open.length > 0 && <span className="chip medium">{open.length}</span>}</h3>
      {open.map((q) => (
        <div key={q.id} className="question" data-testid={`question-${q.id}`}>
          <p><span className="muted">{label(q.field)}:</span> {q.question}</p>
          <div className="row">
            <input style={{ flex: 1, minWidth: 220 }} aria-label="Answer" value={text[q.id] ?? ""}
                   placeholder="the answer, or why it is acceptable" onChange={(e) => setText({ ...text, [q.id]: e.target.value })} />
            <button type="button" className="btn" disabled={busy || !(text[q.id] ?? "").trim()} onClick={() => answer(q.id, "answered")}>
              Answer</button>
            <button type="button" className="btn" disabled={busy || !(text[q.id] ?? "").trim()}
                    onClick={() => answer(q.id, "accepted_as_limitation")}>Accept as a limitation</button>
          </div>
        </div>
      ))}
      {settled.length > 0 && (
        <details>
          <summary className="muted">{settled.length} settled</summary>
          {settled.map((q) => (
            <p key={q.id} className="muted">{label(q.field)}: {q.question} — <em>{q.answer}</em>
              {q.status === "accepted_as_limitation" ? " (a limitation)" : ""}</p>
          ))}
        </details>
      )}
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </section>
  );
}
