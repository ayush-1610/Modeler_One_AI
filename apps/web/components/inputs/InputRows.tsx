"use client";

import { useState } from "react";

import { EmptyState } from "@/components/kit";
import { send, type Schema } from "@/lib/api";

import { Decide, type Ev, LABEL, type Run, Source, TodoAction, TodoCard, type TodoItem, Value } from "./InputsTodo";

export type Row = Schema<"CompoundRow">;
type Alternative = Schema<"AlternativeView">;
// the evidence view's fields (EvidenceView) as the shared fix components read them
const ev = (x: Schema<"EvidenceView">) => x as unknown as Ev;

// what waits on a person first, then the values in the model
const FIRST: Row["state"][] = ["conflict", "held", "missing", "kept"];
const STATE: Record<Row["state"], [string, string]> = {
  kept: ["low", "in the model"], conflict: ["high", "keep one"], held: ["medium", "check it"], missing: ["high", "missing"],
};
// the sources a person may cite for a value typed into a row (modeler_project.evidence.SourceType)
const SOURCE_TYPES = [["PUBLICATION", "publication"], ["CLIENT_REPORT", "client report"], ["REGULATORY_REVIEW", "regulatory review"],
                      ["DATABASE", "database"], ["ASSUMPTION", "assumption (no source)"]] as const;

/** A value with its source, typed into the row (p2-add): filed under the row's data-checklist item, cited. */
function AddValue({ row, projectId, run }: { row: Row; projectId: string; run: Run }) {
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState(row.unit ?? "");
  const [type, setType] = useState<(typeof SOURCE_TYPES)[number][0]>("PUBLICATION");
  const [title, setTitle] = useState("");
  const [link, setLink] = useState("");
  const [quote, setQuote] = useState("");
  const numeric = value.trim() !== "" && !Number.isNaN(Number(value));
  const cited = type === "ASSUMPTION" || link.trim() !== "";
  if (!row.req_id) return <p className="muted" style={{ fontSize: 13, margin: 0 }}>This input has no item on the data checklist to file a value under.</p>;
  return (
    <div className="add-value" data-testid={`add-${row.id}`}>
      <div className="row" style={{ gap: 6 }}>
        <input placeholder="value" value={value} onChange={(e) => setValue(e.target.value)} style={{ width: 110 }} aria-label={`value for ${row.id}`} />
        <input placeholder="unit" value={unit} onChange={(e) => setUnit(e.target.value)} style={{ width: 90 }} aria-label={`unit for ${row.id}`} />
        <select value={type} onChange={(e) => setType(e.target.value as typeof type)} aria-label={`source type for ${row.id}`}>
          {SOURCE_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
        <input placeholder="title" value={title} onChange={(e) => setTitle(e.target.value)} style={{ flex: 1, minWidth: 140 }} aria-label={`title for ${row.id}`} />
        <input placeholder="DOI or URL" value={link} onChange={(e) => setLink(e.target.value)} style={{ width: 170 }} aria-label={`link for ${row.id}`} />
      </div>
      <div className="row" style={{ gap: 6, marginTop: 4 }}>
        <input placeholder="the sentence that states it" value={quote} onChange={(e) => setQuote(e.target.value)} style={{ flex: 1, minWidth: 220 }}
               aria-label={`quote for ${row.id}`} />
        <button className="btn primary" disabled={!value.trim() || !cited}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence", { project_id: projectId }, {
                  req_id: row.req_id as string, target: row.id, value: numeric ? Number(value) : value, unit: unit || null, source_type: type,
                  title, quote, ...(link.startsWith("10.") ? { doi: link } : link ? { url: link } : {}),
                }), `${row.id}: value added with its source.`)}>
          Add
        </button>
      </div>
    </div>
  );
}

/** A source the selection kept or agreed with, and how to exclude it (with a reason; the next best source takes over). */
function SourceLine({ e, projectId, run }: { e: Ev; projectId: string; run: Run }) {
  const [reason, setReason] = useState("");
  return (
    <li className="source-line">
      <Source e={e} />
      <div className="row" style={{ gap: 6, marginTop: 4 }}>
        <input placeholder="why exclude it" value={reason} onChange={(x) => setReason(x.target.value)} style={{ flex: 1, minWidth: 160 }}
               aria-label={`reason to exclude ${e.id}`} />
        <button className="btn" disabled={!reason.trim()}
                onClick={() => void run(() => send("post", "/api/v1/projects/{project_id}/evidence/{evidence_id}:decide",
                                                   { project_id: projectId, evidence_id: e.id }, { state: "REJECTED", reason }),
                                        `${e.id} excluded; the next best source is used.`)}>Exclude</button>
      </div>
    </li>
  );
}

function AlternativeLine({ a }: { a: Alternative }) {
  return (
    <li className="source-line">
      <div className="row" style={{ gap: 8 }}>
        <Value e={ev(a)} />
        <span className={`chip ${a.relation === "conflicts" ? "high" : "medium"}`}>
          {a.relation === "conflicts" ? "more than 2-fold apart" : `differs by ${a.differs_pct} %`}
        </span>
      </div>
      <Source e={ev(a)} />
    </li>
  );
}

function ChooseProcess({ row, projectId, run }: { row: Row; projectId: string; run: Run }) {
  const [value, setValue] = useState(row.candidates[0] ?? "");
  const [reason, setReason] = useState("");
  return (
    <div className="row" style={{ gap: 4 }}>
      <select value={value} onChange={(e) => setValue(e.target.value)} aria-label={`process for ${row.id}`}>
        {row.candidates.map((c) => <option key={c}>{c}</option>)}
      </select>
      <input placeholder="why" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: 150 }} />
      <button className="btn" disabled={!reason.trim()}
              onClick={() => void run(() => send("put", "/api/v1/projects/{project_id}/inputs/choices", { project_id: projectId },
                                                 { kind: "process", key: row.id.split(".").slice(0, -1).join("."), value, reason }),
                                      `${row.id}: carried by ${value}.`)}>Choose</button>
    </div>
  );
}

/** One model input: its value in the PK-Sim unit, the source kept and the sources that agree (D-32), the alternatives
 *  beneath, and what settles it in place when it waits on a person. */
function InputRow({ row, items, projectId, run }: { row: Row; items: TodoItem[]; projectId: string; run: Run }) {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [state, label] = STATE[row.state];
  const kept = row.sources.length ? ev(row.sources[0]) : undefined;
  const agree = row.sources.length - 1;
  return (
    <div className={`input-row ${row.state}`} data-testid={`record-${row.id}`} id={`row-${row.id}`}>
      <div className="input-head">
        <div className="input-name">
          <strong>{LABEL[row.id] ?? row.id}</strong>
          <code className="muted">{row.id}</code>
        </div>
        <div className="input-value">
          {row.value === null ? <span className="muted">—</span>
            : <><strong>{typeof row.value === "number" ? +row.value.toPrecision(5) : row.value}</strong> {row.unit ?? ""}</>}
        </div>
        <div className="input-source">
          {kept ? <>
            {kept.source.title || kept.source_type.toLowerCase().replace(/_/g, " ")}{kept.source.year ? ` · ${kept.source.year}` : ""}
            <span className="muted"> · grade {kept.confidence}</span>
            {row.state === "kept" && agree > 0 && <span className="chip low" title="sources within 10 % of the kept value (D-32)">+{agree} agree</span>}
          </> : row.state === "conflict" ? <span className="muted">{row.alternatives.length} sources disagree</span> : <span className="muted">no source yet</span>}
        </div>
        <div className="input-state">
          <span className={`chip ${state}`}>{label}</span>
          {row.binding && <div className="muted" style={{ fontSize: 12 }} title={row.binding.parameter ?? ""}>{row.binding.process ?? row.binding.parameter}</div>}
        </div>
      </div>
      {row.candidates.length > 0 && !items.some((t) => t.kind === "process") && <ChooseProcess row={row} projectId={projectId} run={run} />}
      {items.map((t) => (
        <div key={`${t.kind}-${t.target}`} className="input-fix" data-testid={`todo-${t.kind}-${t.target}`} id={`todo-${t.kind}-${t.target}`}>
          <TodoAction t={t} projectId={projectId} run={run} />
          {t.kind === "process" && row.candidates.length > 0 && <ChooseProcess row={row} projectId={projectId} run={run} />}
        </div>
      ))}
      {row.state === "held" && items.length === 0 && row.sources.map(ev).map((e) => <Decide key={e.id} e={e} projectId={projectId} run={run} />)}
      <div className="row" style={{ gap: 6 }}>
        {(row.sources.length > 0 || row.alternatives.length > 0) && row.state === "kept" && (
          <button type="button" className="link-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? "Hide the sources" : `Sources (${row.sources.length + row.alternatives.length})`}
          </button>
        )}
        <button type="button" className="link-btn" onClick={() => setAdding(!adding)} data-testid={`add-open-${row.id}`}>
          {adding ? "Cancel" : "Add a value"}</button>
      </div>
      {open && row.state === "kept" && (
        <ul className="sources">
          {row.sources.map(ev).map((e) => <SourceLine key={e.id} e={e} projectId={projectId} run={run} />)}
          {row.alternatives.length > 0 && <li className="muted" style={{ fontSize: 12 }}>Not used (listed for the review):</li>}
          {row.alternatives.map((a) => <AlternativeLine key={a.id} a={a} />)}
        </ul>
      )}
      {adding && <AddValue row={row} projectId={projectId} run={run} />}
    </div>
  );
}

/** The model inputs of one tab, each in its row, with what waits on a person settled where it is. Items about no row
 *  of the tab (a placeholder parameter, a build) come first. */
export function InputRows({ rows, todo, projectId, run, empty }: {
  rows: Row[]; todo: TodoItem[]; projectId: string; run: Run; empty: string;
}) {
  const ids = new Set(rows.map((r) => r.id));
  const loose = todo.filter((t) => !ids.has(t.target));
  return (
    <>
      {loose.map((t, i) => <TodoCard key={`${t.kind}-${t.target}-${i}`} t={t} projectId={projectId} run={run} />)}
      {rows.length === 0 && loose.length === 0
        ? <EmptyState title="Nothing on this tab yet">{empty}</EmptyState>
        : [...rows].sort((a, b) => FIRST.indexOf(a.state) - FIRST.indexOf(b.state)).map((r) => <InputRow key={r.id} row={r} items={todo.filter((t) => t.target === r.id)} projectId={projectId} run={run} />)}
    </>
  );
}

