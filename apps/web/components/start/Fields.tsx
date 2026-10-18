"use client";

// One brief field as Start shows it (redesign §3.1): the value, where it came from, the quote behind it, and an edit
// that asks no "why" (map row p1-why: the version records who changed what). Choices save on a click; text, numbers and
// lists through a small editor.

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import type { useMutation } from "@/lib/hooks";
import { filled, shown, SOURCE_CHIP, SOURCE_LABEL, type Citation, type FieldChange, type StartField } from "@/lib/start";

/** Store brief changes (`PUT /brief`); answers the API's reason when it refuses. */
export type Save = (changes: FieldChange[], reason: string) => Promise<string | null>;
export type OpenQuote = (c: Citation) => void;
export type Run = ReturnType<typeof useMutation>["run"];

export function Quotes({ citations, onOpen }: { citations: Citation[]; onOpen: OpenQuote }) {
  if (!citations.length) return null;
  return (
    <span className="quotes">
      {citations.map((c, i) => (
        <button key={i} type="button" className="cite" title={`${c.source}: “${c.quote}”`} onClick={() => onOpen(c)}>
          {/* a database record has no pages: its locator says it all ("PubChem CID 9887712") */}
          {c.locator.startsWith("PubChem") ? c.locator : `${c.source || "source"} p.${c.page}${c.locator ? ` · ${c.locator}` : ""}`}
        </button>
      ))}
    </span>
  );
}

function Source({ field }: { field: StartField }) {
  const { status, confidence, note } = field.record;
  return (
    <span className={`chip ${SOURCE_CHIP[status] ?? "neutral"}`} title={note || undefined}>
      {SOURCE_LABEL[status] ?? status.toLowerCase()}{confidence && confidence !== "A" ? ` · ${confidence}` : ""}
    </span>
  );
}

/** The editor's input for a field's kind; `value` is what the API takes (a list for multi and list fields). */
function ValueInput({ field, value, onChange, id }: {
  field: StartField; value: unknown; onChange: (v: unknown) => void; id: string;
}) {
  if (field.kind === "multi") {
    const chosen = new Set(Array.isArray(value) ? (value as string[]) : []);
    return (
      <div className="choice-grid" role="group" aria-label={field.label}>
        {field.options.map((o) => (
          <label key={o.value} className={chosen.has(o.value) ? "on" : ""}>
            <input type="checkbox" checked={chosen.has(o.value)} onChange={(e) => {
              const next = new Set(chosen);
              if (e.target.checked) next.add(o.value); else next.delete(o.value);
              onChange(field.options.map((x) => x.value).filter((v) => next.has(v)));
            }} /> {o.label}
          </label>
        ))}
      </div>
    );
  }
  if (field.kind === "list") {
    return <textarea id={id} rows={3} value={Array.isArray(value) ? (value as string[]).join("\n") : String(value ?? "")}
                     placeholder="one item per line" onChange={(e) => onChange(e.target.value.split("\n"))} />;
  }
  if (field.kind === "enum" || field.kind === "bool") {
    const options = field.kind === "bool" ? [{ value: "yes", label: "yes" }, { value: "no", label: "no" }] : field.options;
    const current = field.kind === "bool" ? (value === true ? "yes" : value === false ? "no" : "") : String(value ?? "");
    return (
      <select id={id} value={current} onChange={(e) => onChange(field.kind === "bool" ? e.target.value === "yes" : e.target.value)}>
        <option value="">—</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  }
  if (field.kind === "text" && (field.path.startsWith("qoi.") || field.path.startsWith("m15."))) {
    return <textarea id={id} rows={3} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
  }
  return <input id={id} type={field.kind === "number" ? "number" : "text"} value={String(value ?? "")}
                onChange={(e) => onChange(e.target.value)} />;
}

function cleaned(field: StartField, value: unknown): unknown {
  if (field.kind === "list" && Array.isArray(value)) return (value as string[]).map((v) => v.trim()).filter(Boolean);
  return value;
}

/** A field row: label, value, source and quote, warnings beside it, and an inline editor. */
export function FieldRow({ field, onSave, onOpen, busy, hint, open = false, onClose }: {
  field: StartField; onSave: Save; onOpen: OpenQuote; busy: boolean; hint?: string;
  /** start in the editor (a field added from a list of the ones not stated); `onClose` when it is saved or cancelled */
  open?: boolean; onClose?: () => void;
}) {
  const [editing, setEditingState] = useState(open);
  const setEditing = (on: boolean) => { setEditingState(on); if (!on) onClose?.(); };
  const [value, setValue] = useState<unknown>(field.record.value);
  const [unit, setUnit] = useState(field.record.unit ?? field.unit ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const id = `f-${field.path.replace(/[^a-z0-9]+/gi, "-")}`;

  async function save(change: FieldChange) {
    const failed = await onSave([change], `${field.label}: ${change.status === "EDITED" ? "set" : change.status.toLowerCase().replace("_", " ")} at Start`);
    setProblem(failed);
    if (!failed) setEditing(false);
  }

  return (
    <div className={`field-row${filled(field) ? "" : " empty"}`} data-testid={`field-${field.path}`} id={id}>
      <div className="field-row-head">
        <span className="field-label" title={field.help || undefined}>
          {field.label}{field.required && <span className="req" aria-label="needed"> *</span>}
        </span>
        <Source field={field} />
        {!editing && (
          <button type="button" className="link-btn" data-testid={`edit-${field.path}`} disabled={busy}
                  onClick={() => { setValue(field.record.value); setUnit(field.record.unit ?? field.unit ?? ""); setEditing(true); }}>
            {filled(field) ? "Change" : "Add"}
          </button>
        )}
      </div>
      {!editing && (
        <div className="field-value">
          {shown(field) || <span className="muted">{hint ?? "—"}</span>}
          <Quotes citations={field.record.citations} onOpen={onOpen} />
        </div>
      )}
      {!editing && field.record.note && <div className="field-note">{field.record.note}</div>}
      {editing && (
        <div className="field-editor" data-testid="field-editor">
          <div className="row" style={{ alignItems: "flex-start" }}>
            <div style={{ flex: 1, minWidth: 0 }}><ValueInput field={field} value={value} onChange={setValue} id={`${id}-input`} /></div>
            {field.kind === "number" && (
              <input aria-label="unit" className="unit" value={unit} onChange={(e) => setUnit(e.target.value)} />
            )}
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button type="button" className="btn primary" data-testid="edit-save" disabled={busy}
                    onClick={() => save({ path: field.path, status: "EDITED", value: cleaned(field, value), unit: unit || null })}>
              Save
            </button>
            <button type="button" className="btn" onClick={() => { setEditing(false); setProblem(null); }}>Cancel</button>
            <button type="button" className="link-btn" disabled={busy}
                    onClick={() => save({ path: field.path, status: "NOT_APPLICABLE" })}>Not applicable</button>
            {filled(field) && (
              <button type="button" className="link-btn" disabled={busy}
                      onClick={() => save({ path: field.path, status: "MISSING" })}>Clear</button>
            )}
          </div>
        </div>
      )}
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
      {field.warnings.map((w) => <InlineIssue key={w}>{w}</InlineIssue>)}
    </div>
  );
}

/** A choice saved on a click (the scope gates, the ratings, a scenario's route): each option a button, the builder's
 *  "not supported yet" written on the options it cannot model. */
export function ChoiceField({ field, onSave, onOpen, busy, compact }: {
  field: StartField; onSave: Save; onOpen: OpenQuote; busy: boolean; compact?: boolean;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const yesNo = field.kind === "bool";
  const options = yesNo ? [{ value: "yes", label: "yes", supported: null }, { value: "no", label: "no", supported: null }]
    : field.options;
  const current = !filled(field) ? null : yesNo ? (field.record.value ? "yes" : "no") : String(field.record.value);
  async function choose(value: string) {
    if (value === current) return;
    setProblem(await onSave([{ path: field.path, status: "EDITED", value: yesNo ? value === "yes" : value }],
                            `${field.label}: ${options.find((o) => o.value === value)?.label ?? value} at Start`));
  }
  return (
    <div className={`choice-field${compact ? " compact" : ""}`} data-testid={`field-${field.path}`}>
      <div className="field-row-head">
        <span className="field-label" title={field.help || undefined}>
          {field.label}{field.required && <span className="req" aria-label="needed"> *</span>}
        </span>
        {current && <Source field={field} />}
        <Quotes citations={field.record.citations} onOpen={onOpen} />
      </div>
      <div className="segmented" role="radiogroup" aria-label={field.label}>
        {options.map((o) => (
          <button key={o.value} type="button" role="radio" aria-checked={current === o.value} disabled={busy}
                  className={`${current === o.value ? "on" : ""}${o.supported === false ? " unsupported" : ""}`}
                  data-testid={`choose-${field.path}-${o.value}`} onClick={() => choose(o.value)}
                  title={o.supported === false ? "not supported yet" : undefined}>
            {o.label}{o.supported === false && <span className="tag">not supported yet</span>}
          </button>
        ))}
      </div>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
      {field.warnings.map((w) => <InlineIssue key={w}>{w}</InlineIssue>)}
    </div>
  );
}

/** Several choices (formulation types, pathways, applications): ticked, then saved once. */
export function MultiField({ field, onSave, onOpen, busy }: {
  field: StartField; onSave: Save; onOpen: OpenQuote; busy: boolean;
}) {
  const saved = filled(field) && Array.isArray(field.record.value) ? (field.record.value as string[]) : [];
  const [chosen, setChosen] = useState<string[] | null>(null);   // null: nothing changed since the last save
  const [problem, setProblem] = useState<string | null>(null);
  const now = chosen ?? saved;
  const changed = chosen !== null && (chosen.length !== saved.length || chosen.some((v) => !saved.includes(v)));
  async function save() {
    const failed = await onSave([now.length ? { path: field.path, status: "EDITED", value: now } : { path: field.path, status: "MISSING" }],
                                `${field.label} set at Start`);
    setProblem(failed);
    if (!failed) setChosen(null);
  }
  return (
    <div className="choice-field" data-testid={`field-${field.path}`}>
      <div className="field-row-head">
        <span className="field-label" title={field.help || undefined}>
          {field.label}{field.required && <span className="req" aria-label="needed"> *</span>}
        </span>
        {saved.length > 0 && <Source field={field} />}
        <Quotes citations={field.record.citations} onOpen={onOpen} />
      </div>
      <div className="choice-grid" role="group" aria-label={field.label}>
        {field.options.map((o) => (
          <label key={o.value} className={`${now.includes(o.value) ? "on" : ""}${o.supported === false ? " unsupported" : ""}`}
                 data-testid={`tick-${field.path}-${o.value}`}>
            <input type="checkbox" checked={now.includes(o.value)} disabled={busy} onChange={(e) => {
              const next = new Set(now);
              if (e.target.checked) next.add(o.value); else next.delete(o.value);
              setChosen(field.options.map((x) => x.value).filter((v) => next.has(v)));
            }} />
            <span>{o.label}{o.supported === false && <span className="tag">not supported yet</span>}</span>
          </label>
        ))}
      </div>
      {changed && (
        <div className="row" style={{ marginTop: 8 }}>
          <button type="button" className="btn primary" data-testid={`save-${field.path}`} disabled={busy} onClick={save}>Save</button>
          <button type="button" className="btn" onClick={() => setChosen(null)}>Undo</button>
        </div>
      )}
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
      {field.warnings.map((w) => <InlineIssue key={w}>{w}</InlineIssue>)}
    </div>
  );
}

/** A choice from a longer list (a scenario's route), saved when it changes. */
export function SelectField({ field, onSave, busy, label }: {
  field: StartField; onSave: Save; busy: boolean; label?: string;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const current = filled(field) ? String(field.record.value) : "";
  return (
    <span className="select-field" data-testid={`field-${field.path}`}>
      <select aria-label={label ?? field.label} value={current} disabled={busy} data-testid={`select-${field.path}`}
              onChange={async (e) => setProblem(await onSave(
                [e.target.value ? { path: field.path, status: "EDITED", value: e.target.value } : { path: field.path, status: "MISSING" }],
                `${field.label}: ${e.target.value || "cleared"} at Start`))}>
        <option value="">{label ?? field.label}…</option>
        {field.options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}{o.supported === false ? " (not supported yet)" : ""}</option>
        ))}
      </select>
      {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
    </span>
  );
}
