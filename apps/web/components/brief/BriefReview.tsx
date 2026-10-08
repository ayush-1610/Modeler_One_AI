"use client";

import { Fragment, useMemo, useState } from "react";

import { DocumentViewer } from "@/components/brief/DocumentViewer";
import { Card } from "@/components/ui";
import {
  display, EMPTY_RECORD, STATUS_CHIP,
  type BriefView, type Citation, type DocumentView, type FieldDef, type FieldRecord, type Impact,
} from "@/lib/brief";
import { narrow, send, type Schema } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";

type Focus = { sha256: string; page: number; quote: string | null } | null;
type EditStatus = "EDITED" | "CONFIRMED" | "NOT_APPLICABLE" | "MISSING";
type Change = { path: string; status: EditStatus; value?: unknown; unit?: string | null; note: string };

function CitationChips({ citations, onOpen }: { citations: Citation[]; onOpen: (c: Citation) => void }) {
  if (!citations.length) return null;
  return (
    <span className="row" style={{ gap: 4 }}>
      {citations.map((c, i) => (
        <button key={i} className="cite" title={c.quote} onClick={() => onOpen(c)}>
          {c.source || "source"} p.{c.page}{c.locator ? ` · ${c.locator}` : ""}
        </button>
      ))}
    </span>
  );
}

function ValueInput({ def, value, onChange }: { def: FieldDef; value: unknown; onChange: (v: unknown) => void }) {
  if (def.kind === "enum") {
    return (
      <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {def.options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  }
  if (def.kind === "bool") {
    return (
      <select value={value === true ? "yes" : value === false ? "no" : ""} onChange={(e) => onChange(e.target.value === "yes")}>
        <option value="">—</option><option value="yes">yes</option><option value="no">no</option>
      </select>
    );
  }
  if (def.kind === "multi") {
    const selected = new Set(Array.isArray(value) ? (value as string[]) : []);
    return (
      <div className="multi">
        {def.options.map((o) => (
          <label key={o}>
            <input type="checkbox" checked={selected.has(o)} onChange={(e) => {
              const next = new Set(selected);
              if (e.target.checked) next.add(o); else next.delete(o);
              onChange(Array.from(next));
            }} /> {o}
          </label>
        ))}
      </div>
    );
  }
  if (def.kind === "list") {
    return <textarea rows={3} value={Array.isArray(value) ? (value as string[]).join("; ") : String(value ?? "")}
                     placeholder="items separated by ;" onChange={(e) => onChange(e.target.value)} />;
  }
  return <input type={def.kind === "number" ? "number" : "text"} value={String(value ?? "")}
                onChange={(e) => onChange(e.target.value)} />;
}

function FieldEditor({
  path, def, record, onSave, onPreview, onCancel,
}: {
  path: string;
  def: FieldDef;
  record: FieldRecord;
  onSave: (c: Change) => Promise<string | null>;
  onPreview: (c: Change) => Promise<Impact | string>;
  onCancel: () => void;
}) {
  const [status, setStatus] = useState<EditStatus>(record.status === "MISSING" ? "EDITED" : "EDITED");
  const [value, setValue] = useState<unknown>(record.value);
  const [unit, setUnit] = useState<string>(record.unit ?? def.unit ?? "");
  const [note, setNote] = useState("");
  const [impact, setImpact] = useState<Impact | null>(null);
  const [error, setError] = useState<string | null>(null);
  const change: Change = { path, status, value: status === "EDITED" ? value : undefined, unit: unit || null, note };
  const needsNote = status !== "CONFIRMED";

  return (
    <div className="editor" data-testid="field-editor">
      <div className="row" style={{ alignItems: "flex-start" }}>
        <div className="field" style={{ flex: "0 0 170px" }}>
          <label>Action</label>
          <select value={status} onChange={(e) => setStatus(e.target.value as EditStatus)}>
            <option value="EDITED">set the value</option>
            {record.status !== "MISSING" && <option value="CONFIRMED">confirm as is</option>}
            <option value="NOT_APPLICABLE">not applicable</option>
            <option value="MISSING">clear (missing)</option>
          </select>
        </div>
        {status === "EDITED" && (
          <div className="field" style={{ flex: 1 }}>
            <label>{def.label}</label>
            <ValueInput def={def} value={value} onChange={setValue} />
          </div>
        )}
        {status === "EDITED" && def.kind === "number" && (
          <div className="field" style={{ flex: "0 0 90px" }}>
            <label>Unit</label>
            <input value={unit} onChange={(e) => setUnit(e.target.value)} />
          </div>
        )}
      </div>
      <div className="field">
        <label>Why {needsNote ? "*" : "(optional)"}</label>
        <input data-testid="edit-note" value={note} onChange={(e) => setNote(e.target.value)}
               placeholder="e.g. corrected from the signed protocol, section 4.2" />
      </div>
      {error && <div className="banner err" style={{ marginBottom: 8 }}>{error}</div>}
      {impact && (
        <div className="banner warn" style={{ marginBottom: 8 }}>
          {impact.affected.length === 0 ? "Nothing else depends on the brief yet." : (
            <>This edit makes stale: {impact.affected.map((a) => `${a.ref.kind}/${a.ref.id} (${a.effect})`).join("; ")}</>
          )}
        </div>
      )}
      <div className="row">
        <button className="btn" disabled={needsNote && !note.trim()} onClick={async () => {
          const r = await onPreview(change);
          if (typeof r === "string") setError(r); else { setError(null); setImpact(r); }
        }}>Preview impact</button>
        <button className="btn primary" data-testid="edit-save" disabled={needsNote && !note.trim()} onClick={async () => {
          const r = await onSave(change);
          if (r) setError(r);
        }}>Save</button>
        <button className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function StatusCell({ record }: { record: FieldRecord }) {
  return (
    <span className="row" style={{ gap: 4 }}>
      <span className={`chip ${STATUS_CHIP[record.status]}`}>{record.status.toLowerCase().replace("_", " ")}</span>
      {record.confidence && <span className="chip neutral" title="extraction confidence">{record.confidence}</span>}
    </span>
  );
}

/** Review layer L1 (plan §5.2 P1): the brief beside its sources; every edit says why; approval when nothing blocks. */
export function BriefReview({ projectId }: { projectId: string }) {
  const page = useResource("/api/v1/projects/{project_id}/brief", { project_id: projectId },
    { select: (d) => narrow<BriefView>(d), poll: (d) => d.extraction_running });
  const docs = useResource("/api/v1/projects/{project_id}/documents", { project_id: projectId });
  const { run, busy } = useMutation();
  const [editing, setEditing] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const view = page.data;
  const documents = docs.data?.documents ?? [];

  const defsBySection = useMemo(() => {
    const out: Record<string, FieldDef[]> = {};
    view?.catalog.fields.forEach((f) => { (out[f.section] ??= []).push(f); });
    return out;
  }, [view]);

  if (page.problem) return <div className="banner err">{page.problem}</div>;
  if (!view) return <p className="muted">Loading the brief…</p>;
  const { brief, catalog } = view;

  const open = (c: Citation) => setFocus({ sha256: c.doc_sha256, page: c.page, quote: c.quote });

  async function save(change: Change): Promise<string | null> {
    const { problem } = await run(() => send("put", "/api/v1/projects/{project_id}/brief", { project_id: projectId },
      { changes: [change], reason: change.note || `confirmed ${change.path}` }));
    if (!problem) setEditing(null);
    return problem;
  }

  // a dry run: what the change would make stale; nothing is stored
  async function preview(change: Change): Promise<Impact | string> {
    const env = await send("put", "/api/v1/projects/{project_id}/brief", { project_id: projectId },
      { changes: [change], reason: change.note || "preview", preview: true });
    return env.errors?.length || !env.data ? (env.errors?.[0]?.message ?? "no preview")
      : (env.data as Schema<"BriefImpact">).impact;
  }

  async function extract() {
    const { data, problem } = await run(() => send("post", "/api/v1/projects/{project_id}/brief:extract", { project_id: projectId }, {}));
    setNotice(problem
      ?? (data?.agents ? "The intake agent is reading the documents; the brief refreshes as it finishes."
        : (data?.problem ?? "Identity resolved; fill the brief by hand.")));
  }

  async function approve() {
    const { problem } = await run(() => send("post", "/api/v1/projects/{project_id}/brief:approve", { project_id: projectId }, { note: "" }));
    setNotice(problem ?? "Brief approved.");
  }

  async function answer(questionId: string, text: string, status: "answered" | "accepted_as_limitation") {
    const { problem } = await run(() => send("post", "/api/v1/projects/{project_id}/brief/questions/{question_id}",
      { project_id: projectId, question_id: questionId }, { answer: text, status }));
    if (problem) setNotice(problem);
  }

  async function removeItem(group: string, index: number) {
    const reason = window.prompt(`Why remove ${group} ${index + 1}?`);
    if (!reason) return;
    const { problem } = await run(() => send("post", "/api/v1/projects/{project_id}/brief/items:remove", { project_id: projectId },
      { group, index, reason }));
    if (problem) setNotice(problem);
  }

  const approved = view.artifact.status === "APPROVED";
  const editor = (path: string, def: FieldDef, record: FieldRecord) => editing === path && (
    <tr><td colSpan={5}><FieldEditor path={path} def={def} record={record} onSave={save} onPreview={preview}
                                      onCancel={() => setEditing(null)} /></td></tr>
  );

  return (
    <>
      <Card>
        <div className="spread">
          <div>
            <h2 style={{ margin: 0 }} data-testid="brief-title">Project Brief · {brief.drug_name}</h2>
            <p className="muted" data-testid="brief-version" style={{ margin: "4px 0 0" }}>
              v{view.artifact.version} · {view.artifact.status.toLowerCase()} · last change: {view.artifact.reason}
              {" · "}{Object.entries(view.summary.by_status).map(([k, v]) => `${v} ${k.toLowerCase().replace("_", " ")}`).join(", ")}
            </p>
          </div>
          <div className="row">
            <span className={`chip ${view.agents.enabled ? "brand" : "neutral"}`}
                  title={view.agents.problem ?? ""}>
              {view.agents.enabled ? `agent: ${view.agents.provider} · ${view.agents.model}` : "agents off"}
            </span>
            <button className="btn" disabled={busy || view.extraction_running} onClick={extract}>
              {view.extraction_running ? "Extracting…" : "Run extraction"}
            </button>
            <button className="btn primary" disabled={busy || view.blocking > 0 || approved} onClick={approve}
                    title={view.blocking > 0 ? `${view.blocking} item(s) block approval` : ""}>
              {approved ? "Approved" : `Approve brief${view.blocking ? ` (${view.blocking} open)` : ""}`}
            </button>
          </div>
        </div>
        {notice && <div className="banner ok" style={{ marginTop: 10 }}>{notice}</div>}
        {view.artifact.stale_reasons.length > 0 && (
          <div className="banner warn" style={{ marginTop: 10 }}>Stale: {view.artifact.stale_reasons.join("; ")}</div>
        )}
        {view.runs[0] && (
          <p className="muted" style={{ margin: "8px 0 0", fontSize: 13 }}>
            Last agent run {view.runs[0].run_id}: {view.runs[0].status.toLowerCase()}
            {typeof view.runs[0].summary.accepted === "number" &&
              ` · ${view.runs[0].summary.accepted} fields accepted, ${view.runs[0].summary.rejected} rejected by the citation check`}
          </p>
        )}
      </Card>

      <div className="brief-layout">
        <div>
          {Object.entries(catalog.sections).map(([code, title]) => {
            const fields = defsBySection[code] ?? [];
            const groups = catalog.groups.filter((g) => g.section === code);
            if (code === "J") {
              return (
                <Card key={code} title={`${code} · ${title}`}>
                  {brief.questions.length === 0 ? <p className="muted" style={{ margin: 0 }}>No questions.</p> : (
                    brief.questions.map((q) => <QuestionRow key={q.id} q={q} onAnswer={answer} />)
                  )}
                </Card>
              );
            }
            if (!fields.length && !groups.length) return null;
            return (
              <Card key={code} title={`${code} · ${title}`}>
                {fields.length > 0 && (
                  <table className="brief-table">
                    <tbody>
                      {fields.map((def) => {
                        const record = brief.fields[def.id] ?? EMPTY_RECORD;
                        const issue = view.issues.find((i) => i.path === def.id);
                        return (
                          <Fragment key={def.id}>
                            <tr className={issue ? "has-issue" : ""} data-testid={`field-${def.id}`}>
                              <th scope="row" title={def.help}>{def.label}{def.required ? " *" : ""}</th>
                              <td>{display(record) || <span className="muted">—</span>}
                                {record.note && <div className="muted note">{record.note}</div>}</td>
                              <td><StatusCell record={record} /></td>
                              <td><CitationChips citations={record.citations} onOpen={open} /></td>
                              <td className="num"><button className="btn" data-testid={`edit-${def.id}`} onClick={() => setEditing(editing === def.id ? null : def.id)}>Edit</button></td>
                            </tr>
                            {editor(def.id, def, record)}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                )}
                {groups.map((g) => {
                  const items = brief.groups[g.id] ?? [];
                  const first = g.fields.find((f) => f.required) ?? g.fields[0];
                  return (
                    <div key={g.id} style={{ marginTop: fields.length ? 16 : 0 }}>
                      <div className="spread">
                        <h3 style={{ margin: "0 0 6px" }}>{g.label}{g.required ? " *" : ""}</h3>
                        <button className="btn" onClick={() => setEditing(`${g.id}[${items.length}].${first.id}`)}>Add</button>
                      </div>
                      <div style={{ overflowX: "auto" }}>
                        <table className="group-table">
                          <thead><tr><th>#</th>{g.fields.map((f) => <th key={f.id}>{f.label}{f.required ? " *" : ""}</th>)}<th /></tr></thead>
                          <tbody>
                            {items.map((item, index) => (
                              <tr key={index}>
                                <td className="muted">{index + 1}</td>
                                {g.fields.map((f) => {
                                  const record = item[f.id] ?? EMPTY_RECORD;
                                  const path = `${g.id}[${index}].${f.id}`;
                                  return (
                                    <td key={f.id} className={`cell-${record.status.toLowerCase()}`}>
                                      <button className="cell" onClick={() => setEditing(path)} title={record.citations[0]?.quote ?? record.note}>
                                        {display(record) || "—"}
                                      </button>
                                      {record.citations[0] && <button className="cite dot" onClick={() => open(record.citations[0])}>p.{record.citations[0].page}</button>}
                                    </td>
                                  );
                                })}
                                <td><button className="btn" onClick={() => removeItem(g.id, index)}>×</button></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      {editing?.startsWith(`${g.id}[`) && (() => {
                        const match = /^([a-z_]+)\[(\d+)\]\.([a-z0-9_]+)$/.exec(editing);
                        if (!match) return null;
                        const def = g.fields.find((f) => f.id === match[3])!;
                        const record = (items[Number(match[2])] ?? {})[match[3]] ?? EMPTY_RECORD;
                        return <FieldEditor path={editing} def={def} record={record} onSave={save} onPreview={preview}
                                            onCancel={() => setEditing(null)} />;
                      })()}
                    </div>
                  );
                })}
              </Card>
            );
          })}
          {view.issues.length > 0 && (
            <Card title={`What blocks approval (${view.issues.length})`}>
              <ul className="issues">
                {view.issues.map((i, n) => <li key={n}><code>{i.path}</code> {i.message}</li>)}
              </ul>
            </Card>
          )}
        </div>
        <div className="brief-side">
          {documents.length > 0
            ? <DocumentViewer projectId={projectId} documents={documents} focus={focus} />
            : <Card><p className="muted" style={{ margin: 0 }}>No documents uploaded.</p></Card>}
        </div>
      </div>
    </>
  );
}

function QuestionRow({ q, onAnswer }: {
  q: BriefView["brief"]["questions"][number];
  onAnswer: (id: string, text: string, status: "answered" | "accepted_as_limitation") => void;
}) {
  const [text, setText] = useState(q.answer);
  return (
    <div className="question">
      <div className="row"><code>{q.field}</code><span className={`chip ${q.status === "open" ? "high" : "low"}`}>{q.status.replace(/_/g, " ")}</span></div>
      <p style={{ margin: "6px 0" }}>{q.question}</p>
      {q.status === "open" ? (
        <div className="row">
          <input style={{ flex: 1 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="Answer, or why it is acceptable" />
          <button className="btn" disabled={!text.trim()} onClick={() => onAnswer(q.id, text, "answered")}>Answer</button>
          <button className="btn" disabled={!text.trim()} onClick={() => onAnswer(q.id, text, "accepted_as_limitation")}>Accept as limitation</button>
        </div>
      ) : <p className="muted" style={{ margin: 0 }}>{q.answer}</p>}
    </div>
  );
}
