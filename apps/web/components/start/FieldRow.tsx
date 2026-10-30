"use client";

import { useState, type ReactNode } from "react";

import { InlineIssue } from "@/components/kit";
import { display, type FieldDef, type FieldRecord, type Question } from "@/lib/brief";
import type { Answer, BriefChange, Open, Save } from "@/lib/start";

/** What a box still needs from the person, in red with a warning sign (page review 1: the side panel is gone; Start
 *  cannot be left until these are resolved). */
export function NeedsYou({ issues, testId }: { issues: string[]; testId?: string }) {
  if (!issues.length) return null;
  return (
    <div className="needs-you" data-testid={testId}>
      {issues.map((m) => <InlineIssue key={m} severity="error"><span aria-hidden>⚠ </span>{m}</InlineIssue>)}
    </div>
  );
}

/** An open question on a field, answered (or accepted as a limitation) where the field is. */
export function QuestionRow({ q, onAnswer }: { q: Question; onAnswer: Answer }) {
  const [text, setText] = useState("");
  return (
    <div className="start-question needs-you" data-testid={`question-${q.id}`}>
      <p><span aria-hidden>⚠ </span>{q.question}</p>
      <div className="row">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="The answer, or why it is acceptable" />
        <button type="button" className="btn" disabled={!text.trim()} onClick={() => onAnswer(q.id, text, "answered")}>Answer</button>
        <button type="button" className="btn" disabled={!text.trim()}
                onClick={() => onAnswer(q.id, text, "accepted_as_limitation")}>Accept as a limitation</button>
      </div>
    </div>
  );
}

/** Where a value came from: its quotes (opened in the document viewer), or who set it. An agent's draft says so, and
 *  names the quotes it was built from. */
export function Source({ record, open }: { record: FieldRecord; open: Open }) {
  if (record.status === "DRAFTED") {
    return (
      <span className="sb-source" title={record.note}>
        <span className="chip medium">draft</span> by the intake agent{record.citations.length ? ", from " : ""}
        {record.citations.map((c, i) => (
          <button key={i} type="button" className="cite" title={c.quote} onClick={() => open(c)}>
            {c.source || "source"} p.{c.page}{c.locator ? ` · ${c.locator}` : ""}
          </button>
        ))}
      </span>
    );
  }
  if (record.citations.length) {
    const first = record.citations[0];
    return (
      <span className="sb-source">
        {record.citations.map((c, i) => (
          <button key={i} type="button" className="cite" title={c.quote} onClick={() => open(c)}>
            {c.source || "source"} p.{c.page}{c.locator ? ` · ${c.locator}` : ""}
          </button>
        ))}
        {record.status === "EXTRACTED" && <q className="sb-quote">{first.quote.length > 160 ? `${first.quote.slice(0, 157)}…` : first.quote}</q>}
      </span>
    );
  }
  if (record.status === "COMPUTED") return <span className="sb-source muted" title={record.note}>computed: {record.note}</span>;
  if (record.by && record.status !== "MISSING") {
    return <span className="sb-source muted">{record.status === "ENTERED" ? "entered" : "set"} by {record.by}</span>;
  }
  return null;
}

/** A choice of a few options as one row of buttons (ratings, gates). */
export function Seg({ options, value, labels, onPick, disabled, testId }: {
  options: string[]; value: unknown; labels?: Record<string, string>; onPick: (option: string) => void;
  disabled?: boolean; testId?: string;
}) {
  return (
    <div className="seg" role="group" data-testid={testId}>
      {options.map((o) => (
        <button key={o} type="button" aria-pressed={value === o} disabled={disabled} onClick={() => onPick(o)}
                data-testid={testId ? `${testId}-${o}` : undefined}>{labels?.[o] ?? o.replace(/_/g, " ")}</button>
      ))}
    </div>
  );
}

/** A list of names: each a chip that can be removed, and a box to add one (with suggestions). */
function ChipList({ value, onChange, suggestions, testId }: {
  value: string[]; onChange: (v: string[]) => void; suggestions?: string[]; testId?: string;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const name = draft.trim();
    if (name && !value.includes(name)) onChange([...value, name]);
    setDraft("");
  };
  const list = testId ? `${testId}-options` : undefined;
  return (
    <div className="chip-list">
      {value.map((v) => (
        <span key={v} className="chip neutral">{v}
          <button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(value.filter((x) => x !== v))}>×</button>
        </span>
      ))}
      <input value={draft} list={list} data-testid={testId} placeholder="add one" onChange={(e) => setDraft(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
      {list && <datalist id={list}>{(suggestions ?? []).map((s) => <option key={s} value={s} />)}</datalist>}
      <button type="button" className="btn" onClick={add} disabled={!draft.trim()}>Add</button>
    </div>
  );
}

export function ValueInput({ def, value, onChange, suggestions, testId }: {
  def: FieldDef; value: unknown; onChange: (v: unknown) => void; suggestions?: string[]; testId?: string;
}) {
  const label = (o: string) => def.option_labels[o] ?? o.replace(/_/g, " ");
  if (def.kind === "enum") {
    return (
      <select value={String(value ?? "")} data-testid={testId} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">—</option>
        {def.options.map((o) => <option key={o} value={o}>{label(o)}</option>)}
      </select>
    );
  }
  if (def.kind === "bool") {
    return <Seg options={["yes", "no"]} value={value === true ? "yes" : value === false ? "no" : null}
                onPick={(o) => onChange(o === "yes")} testId={testId} />;
  }
  if (def.kind === "multi") {
    const chosen = new Set(Array.isArray(value) ? (value as string[]) : []);
    return (
      <div className="choice-grid" data-testid={testId}>
        {def.options.map((o) => (
          <label key={o} className={chosen.has(o) ? "on" : ""}>
            <input type="checkbox" checked={chosen.has(o)} onChange={(e) => {
              const next = new Set(chosen);
              if (e.target.checked) next.add(o); else next.delete(o);
              onChange(def.options.filter((x) => next.has(x)));
            }} /> {label(o)}
          </label>
        ))}
      </div>
    );
  }
  if (def.kind === "list") {
    return <ChipList value={Array.isArray(value) ? (value as string[]) : []} onChange={onChange} suggestions={suggestions}
                     testId={testId} />;
  }
  if (def.kind === "number") {
    return <input type="number" value={String(value ?? "")} data-testid={testId} onChange={(e) => onChange(e.target.value)} />;
  }
  return <textarea rows={2} value={String(value ?? "")} data-testid={testId} onChange={(e) => onChange(e.target.value)} />;
}

/** One field of the brief: its value with where it came from, and an edit in place. No reason is asked (D-27): the
 *  record keeps who changed it and when. */
export function FieldRow({ path, def, record, save, open, allowNotApplicable, suggestions, extra, issues = [], questions = [],
  onAnswer, confirmable }: {
  path: string; def: FieldDef; record: FieldRecord; save: Save; open: Open; allowNotApplicable?: boolean;
  suggestions?: string[]; extra?: ReactNode;
  /** A field that needs a person's word: an agent's draft or a document's value is confirmed (kept as it is) here. */
  confirmable?: boolean;
  /** What this field still needs (Start's issues on it) and its open questions, marked in red on the row. */
  issues?: string[]; questions?: Question[]; onAnswer?: Answer;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState<unknown>(record.value);
  const [problem, setProblem] = useState<string | null>(null);
  const shown = display(record, def);

  async function commit(change: BriefChange) {
    const refused = await save([change]);
    setProblem(refused);
    if (!refused) setEditing(false);
  }

  return (
    <div className={`sb-row${record.status === "MISSING" ? " missing" : ""}${issues.length || questions.length ? " needs-you" : ""}`}
         data-testid={`start-field-${path}`}>
      <div className="sb-label" title={def.help}>{def.label}</div>
      <div className="sb-value">
        {editing ? (
          <div className="sb-editor">
            <ValueInput def={def} value={value} onChange={setValue} suggestions={suggestions} testId={`input-${path}`} />
            <div className="row">
              <button type="button" className="btn primary" data-testid={`save-${path}`}
                      onClick={() => commit({ path, status: "EDITED", value })}>Save</button>
              {allowNotApplicable && (
                <button type="button" className="btn" onClick={() => commit({ path, status: "NOT_APPLICABLE" })}>Not applicable</button>
              )}
              <button type="button" className="btn" onClick={() => { setEditing(false); setProblem(null); }}>Cancel</button>
            </div>
            {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
          </div>
        ) : (
          <>
            {shown ? <span className="sb-text">{shown}</span>
              : <span className="sb-missing">{record.status === "NOT_APPLICABLE" ? "not applicable" : "not set"}</span>}
            <Source record={record} open={open} />
            {extra}
          </>
        )}
        <NeedsYou issues={issues} />
        {onAnswer && questions.map((q) => <QuestionRow key={q.id} q={q} onAnswer={onAnswer} />)}
      </div>
      {!editing && (
        <div className="sb-actions">
          {confirmable && shown && (record.status === "DRAFTED" || record.status === "EXTRACTED") && (
            <button type="button" className="btn primary" data-testid={`confirm-${path}`}
                    onClick={() => commit({ path, status: "CONFIRMED" })}>Confirm</button>
          )}
          <button type="button" className="btn sb-change" data-testid={`edit-${path}`}
                  onClick={() => { setValue(record.value); setProblem(null); setEditing(true); }}>{shown ? "Change" : "Set"}</button>
        </div>
      )}
    </div>
  );
}
